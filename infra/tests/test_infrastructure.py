"""Offline contract checks against real `az bicep build` output.

No Azure SDK, authentication, network requests, ARM expression execution, or
third-party test/lint dependencies. This is not a replacement for live preflight.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys
import unittest


INFRA = Path(__file__).resolve().parents[1]
TEMPLATE_PATH: Path


def declarations(template: dict, resource_type: str | None = None) -> list[dict]:
    resources = template.get("resources", [])
    if isinstance(resources, dict):
        resources = list(resources.values())
    return [
        resource
        for resource in resources
        if not resource.get("existing", False)
        and (resource_type is None or resource["type"].lower() == resource_type.lower())
    ]


def deployment(template: dict, name: str) -> dict:
    return next(
        resource
        for resource in declarations(template, "Microsoft.Resources/deployments")
        if resource["name"] == name
    )


def child(template: dict, name: str) -> dict:
    return deployment(template, name)["properties"]["template"]


def bindings(template: dict, name: str) -> dict:
    return {
        name: parameter["value"]
        for name, parameter in deployment(template, name)["properties"]["parameters"].items()
    }


def only(template: dict, resource_type: str) -> dict:
    resources = declarations(template, resource_type)
    if len(resources) != 1:
        raise AssertionError(f"Expected one {resource_type}, got {len(resources)}")
    return resources[0]


def all_templates(template: dict):
    yield template
    for resource in declarations(template, "Microsoft.Resources/deployments"):
        nested = resource.get("properties", {}).get("template")
        if isinstance(nested, dict):
            yield from all_templates(nested)


class InfrastructureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8-sig"))
        cls.resources = child(cls.root, "private-foundry-resources")
        cls.network = child(cls.resources, "customer-network")
        cls.firewall = child(cls.network, "egress-firewall")
        cls.services = child(cls.resources, "private-services")
        cls.links = child(cls.resources, "private-links-and-dns")
        cls.managed = child(cls.resources, "foundry-managed-network")
        cls.roles = child(cls.resources, "operator-and-vm-roles")

    def test_subscription_scope_and_exactly_one_resource_group(self):
        self.assertIn("subscriptionDeploymentTemplate", self.root["$schema"])
        group = only(self.root, "Microsoft.Resources/resourceGroups")
        self.assertIn("environmentName", group["name"])
        self.assertIn("location", group["location"])
        self.assertIn("azd-env-name", self.root["variables"]["tags"])

    def test_required_azd_bindings_do_not_silently_fall_back(self):
        parameter_file = json.loads((INFRA / "main.parameters.json").read_text())
        self.assertEqual(
            {name: item["value"] for name, item in parameter_file["parameters"].items()},
            {
                "environmentName": "${AZURE_ENV_NAME}",
                "location": "${AZURE_LOCATION}",
                "networkMode": "${FOUNDRY_NETWORK_MODE}",
                "principalId": "${AZURE_PRINCIPAL_ID}",
                "vmAdminPassword": "${WINDOWS_ADMIN_PASSWORD}",
            },
        )
        for name in ("environmentName", "location", "principalId"):
            self.assertGreater(self.root["parameters"][name]["minLength"], 0)
        self.assertEqual(self.root["parameters"]["principalId"]["minLength"], 36)
        self.assertNotIn("defaultValue", self.root["parameters"]["principalId"])

    def test_password_is_secure_required_and_never_output(self):
        password = self.root["parameters"]["vmAdminPassword"]
        self.assertEqual(password["type"].lower(), "securestring")
        self.assertNotIn("defaultValue", password)
        self.assertGreaterEqual(password["minLength"], 12)
        for template in all_templates(self.root):
            for name in template.get("outputs", {}):
                self.assertIsNone(re.search("password|secret|accesskey|connectionstring", name, re.I))

    def test_no_key_retrieval_or_random_names_anywhere_in_compiled_tree(self):
        text = json.dumps(self.root)
        for forbidden in ("listKeys(", "listAccountSas(", "utcNow(", "newGuid("):
            self.assertNotIn(forbidden.lower(), text.lower())
        self.assertIsNone(re.search(r"/subscriptions/[0-9a-fA-F-]{36}", text))

    def test_all_twenty_two_required_nonsecret_outputs(self):
        required = {
            "AZURE_RESOURCE_GROUP", "FOUNDRY_NETWORK_MODE",
            "AZURE_AI_ACCOUNT_NAME", "AZURE_AI_ACCOUNT_ID",
            "AZURE_AI_PROJECT_NAME", "AZURE_AI_PROJECT_ID", "AZURE_AI_PROJECT_ENDPOINT",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME", "CONTENT_UNDERSTANDING_ENDPOINT",
            "CU_COMPLETION_DEPLOYMENT", "CU_EMBEDDING_DEPLOYMENT",
            "CU_COMPLETION_MODEL_NAME", "CU_EMBEDDING_MODEL_NAME",
            "DOCUMENT_STORAGE_ACCOUNT_NAME", "DOCUMENT_STORAGE_ACCOUNT_ID",
            "DOCUMENT_BLOB_ENDPOINT", "DOCUMENT_CONTAINER_NAME",
            "VM_NAME", "VM_ID", "VM_PRINCIPAL_ID", "BASTION_NAME", "PRIVATE_ADDRESS_PREFIX",
        }
        self.assertEqual(set(self.root["outputs"]), required)
        self.assertTrue(all(item["type"] == "string" for item in self.root["outputs"].values()))

    def test_cu_model_names_are_independent_of_deployment_aliases(self):
        expected_parameters = {
            "CU_COMPLETION_MODEL_NAME": "completionModelName",
            "CU_EMBEDDING_MODEL_NAME": "embeddingModelName",
            "CU_COMPLETION_DEPLOYMENT": "completionDeploymentName",
            "CU_EMBEDDING_DEPLOYMENT": "embeddingDeploymentName",
        }
        for output, parameter in expected_parameters.items():
            self.assertEqual(
                self.root["outputs"][output]["value"],
                f"[parameters('{parameter}')]",
            )

    def test_current_model_and_location_defaults(self):
        params = self.root["parameters"]
        expected = {
            "location": "southcentralus",
            "vmSize": "Standard_D2s_v5",
            "vmAdminUsername": "demoadmin",
            "completionModelName": "gpt-5.2",
            "completionModelVersion": "2025-12-11",
            "completionModelCapacity": 30,
            "embeddingModelName": "text-embedding-3-large",
            "embeddingModelVersion": "1",
            "embeddingModelCapacity": 10,
        }
        for name, value in expected.items():
            self.assertEqual(params[name]["defaultValue"], value)
        models = child(self.resources, "model-deployments")
        self.assertEqual(len(declarations(models, "Microsoft.CognitiveServices/accounts/deployments")), 2)
        for item in declarations(models):
            self.assertEqual(item["properties"]["versionUpgradeOption"], "NoAutoUpgrade")

    def test_both_modes_and_disjoint_default_cidrs(self):
        self.assertEqual(self.root["parameters"]["networkMode"]["allowedValues"], ["byo", "managed"])
        self.assertNotIn("defaultValue", self.root["parameters"]["networkMode"])
        default = self.root["parameters"]["privateAddressPrefix"]["defaultValue"]
        self.assertIn("equals(parameters('networkMode'), 'byo')", default)
        networks = [ipaddress.ip_network("10.42.0.0/16"), ipaddress.ip_network("10.43.0.0/16")]
        for network in networks:
            self.assertIn(str(network), default)
        self.assertFalse(networks[0].overlaps(networks[1]))

    def test_six_nonoverlapping_subnets_in_both_modes(self):
        for prefix in ("10.42.0.0/16", "10.43.0.0/16"):
            with self.subTest(mode_prefix=prefix):
                vnet = ipaddress.ip_network(prefix)
                small = list(vnet.subnets(new_prefix=26))
                large = list(vnet.subnets(new_prefix=24))
                subnets = large[:3] + small[12:15]
                self.assertEqual([n.prefixlen for n in subnets], [24, 24, 24, 26, 26, 26])
                for index, left in enumerate(subnets):
                    for right in subnets[index + 1:]:
                        self.assertFalse(left.overlaps(right))
        for name, length, index in (
            ("windowsPrefix", 24, 0), ("privateEndpointPrefix", 24, 1),
            ("agentPrefix", 24, 2), ("bastionPrefix", 26, 12),
            ("firewallPrefix", 26, 13), ("firewallManagementPrefix", 26, 14),
        ):
            self.assertEqual(
                self.network["variables"][name],
                f"[cidrSubnet(parameters('privateAddressPrefix'), {length}, {index})]",
            )

    def test_workload_routes_use_the_real_firewall_ip(self):
        route = only(self.network, "Microsoft.Network/routeTables")
        self.assertTrue(route["properties"]["disableBgpRoutePropagation"])
        self.assertEqual(len(route["properties"]["routes"]), 1)
        default = route["properties"]["routes"][0]["properties"]
        self.assertEqual(default["addressPrefix"], "0.0.0.0/0")
        self.assertEqual(default["nextHopType"], "VirtualAppliance")
        self.assertIn("egress-firewall", default["nextHopIpAddress"])
        self.assertIn("outputs.privateIpAddress", default["nextHopIpAddress"])
        subnets = declarations(self.network, "Microsoft.Network/virtualNetworks/subnets")
        self.assertEqual(len(subnets), 2)
        for subnet in subnets:
            self.assertFalse(subnet["properties"]["defaultOutboundAccess"])
            self.assertIn("Microsoft.Network/routeTables", subnet["properties"]["routeTable"]["id"])
        agent = next(item for item in subnets if "'agents'" in item["name"])
        self.assertEqual(
            agent["properties"]["delegations"][0]["properties"]["serviceName"],
            "Microsoft.App/environments",
        )

    def test_vm_is_private_windows_2022_with_trusted_launch(self):
        vm = bindings(child(self.resources, "windows-client"), "private-windows-vm")
        self.assertEqual(vm["osType"], "Windows")
        self.assertEqual(vm["securityType"], "TrustedLaunch")
        self.assertTrue(vm["secureBootEnabled"])
        self.assertTrue(vm["vTpmEnabled"])
        self.assertEqual(vm["managedIdentities"], {"systemAssigned": True})
        self.assertEqual(vm["imageReference"]["offer"], "WindowsServer")
        self.assertEqual(self.root["parameters"]["vmImageSku"]["defaultValue"], "2022-datacenter-azure-edition")
        self.assertFalse(vm["bootDiagnostics"])
        self.assertFalse(vm["extensionAntiMalwareConfig"]["enabled"])
        for nic in vm["nicConfigurations"]:
            self.assertFalse(nic["enableIPForwarding"])
            for config in nic["ipConfigurations"]:
                self.assertNotIn("pipConfiguration", config)

    def test_bastion_and_firewall_have_exactly_three_configured_public_ips(self):
        bastion = bindings(self.network, "bastion")
        self.assertEqual(bastion["skuName"], "Standard")
        native = only(child(self.network, "bastion"), "Microsoft.Network/bastionHosts")
        self.assertIn(
            "'enableTunneling', if(equals(parameters('skuName'), 'Standard'), true()",
            native["properties"],
        )
        self.assertFalse(bastion["enableSessionRecording"])
        self.assertEqual(bastion["publicIPAddressObject"]["skuName"], "Standard")
        self.assertEqual(bastion["publicIPAddressObject"]["publicIPAllocationMethod"], "Static")
        ips = declarations(self.firewall, "Microsoft.Network/publicIPAddresses")
        self.assertEqual(len(ips), 2)
        for ip in ips:
            self.assertEqual(ip["sku"]["name"], "Standard")
            self.assertEqual(ip["properties"]["publicIPAllocationMethod"], "Static")
        firewall = only(self.firewall, "Microsoft.Network/azureFirewalls")["properties"]
        self.assertEqual(firewall["sku"], {"name": "AZFW_VNet", "tier": "Basic"})
        self.assertIn("managementIpConfiguration", firewall)
        self.assertIn("managementSubnetId", firewall["managementIpConfiguration"]["properties"]["subnet"]["id"])

    def test_implicit_vm_os_disk_is_also_environment_tagged(self):
        windows = child(self.resources, "windows-client")
        tags = only(windows, "Microsoft.Resources/tags")
        self.assertIn("Microsoft.Compute/disks", tags["scope"])
        self.assertIn("osdisk-", tags["scope"])
        self.assertIn("private-windows-vm", json.dumps(tags["dependsOn"]))
        self.assertIn("parameters('tags')", tags["properties"]["tags"])

    def test_rdp_only_from_bastion_and_explicit_platform_flows(self):
        security = child(self.network, "subnet-security")
        nsgs = declarations(security, "Microsoft.Network/networkSecurityGroups")
        windows = next(nsg for nsg in nsgs if "-windows" in nsg["name"])
        rules = {rule["name"]: rule["properties"] for rule in windows["properties"]["securityRules"]}
        inbound = [rule for rule in rules.values() if rule["direction"] == "Inbound" and rule["access"] == "Allow"]
        self.assertEqual(len(inbound), 1)
        self.assertEqual(inbound[0]["destinationPortRange"], "3389")
        self.assertIn("bastionPrefix", inbound[0]["sourceAddressPrefix"])
        self.assertEqual(rules["AzureDns"]["destinationAddressPrefix"], "AzurePlatformDNS")
        self.assertEqual(rules["ManagedIdentityMetadata"]["destinationAddressPrefix"], "AzurePlatformIMDS")
        self.assertEqual(rules["AzureVmAgentWireServer"]["destinationAddressPrefix"], "168.63.129.16")
        for nsg in nsgs:
            rules = {rule["name"]: rule["properties"] for rule in nsg["properties"]["securityRules"]}
            for name in ("DenyAllOtherInbound", "DenyAllOtherOutbound"):
                self.assertEqual(rules[name]["access"], "Deny")
                self.assertLess(rules[name]["priority"], 65000)

    def test_firewall_basic_uses_supported_controls_and_no_open_destination(self):
        policy = only(self.firewall, "Microsoft.Network/firewallPolicies")["properties"]
        self.assertEqual(policy["sku"]["tier"], "Basic")
        self.assertNotIn("dnsSettings", policy)
        collections = only(self.firewall, "Microsoft.Network/firewallPolicies/ruleCollectionGroups")["properties"]["ruleCollections"]
        for collection in collections:
            self.assertEqual(collection["action"]["type"], "Allow")
            for rule in collection["rules"]:
                self.assertNotEqual(rule.get("destinationAddresses"), ["*"])
                self.assertNotEqual(rule.get("sourceAddresses"), ["*"])
                self.assertNotEqual(rule.get("targetFqdns"), ["*"])
                self.assertNotIn("destinationFqdns", rule)
        text = json.dumps(self.firewall["variables"])
        self.assertNotIn("*.blob.core.windows.net", text)
        self.assertNotIn("*.azurecr.io", text)

    def test_windows_bootstrap_hosts_are_explicit_and_vm_only(self):
        required_hosts = {
            "aka.ms",
            "azcliprod.blob.core.windows.net",
            "github.com",
            "api.github.com",
            "raw.githubusercontent.com",
            "codeload.github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        }
        vm_hosts = set(self.firewall["variables"]["vmSetupFqdns"])
        self.assertTrue(required_hosts.issubset(vm_hosts))
        self.assertTrue(all("*" not in host for host in vm_hosts))
        self.assertEqual(
            {host for host in vm_hosts if host.endswith(".blob.core.windows.net")},
            {"azcliprod.blob.core.windows.net"},
        )
        for host in required_hosts:
            self.assertNotIn(host, self.firewall["variables"]["agentFqdns"])
            self.assertNotIn(host, self.managed["variables"]["agentFqdns"])
        collections = only(
            self.firewall, "Microsoft.Network/firewallPolicies/ruleCollectionGroups"
        )["properties"]["ruleCollections"]
        installer_rule = next(
            rule
            for collection in collections
            for rule in collection["rules"]
            if rule["name"] == "approved-installers-and-repository"
        )
        self.assertEqual(installer_rule["targetFqdns"], "[variables('vmSetupFqdns')]")
        self.assertEqual(installer_rule["sourceAddresses"], ["[parameters('windowsPrefix')]"])
        self.assertEqual(installer_rule["protocols"], [{"protocolType": "Https", "port": 443}])
        self.assertIn("www.microsoft.com", self.firewall["variables"]["certificateFqdns"])
        self.assertNotIn("www.microsoft.com", self.managed["variables"]["agentFqdns"])
        certificate_rule = next(
            rule
            for collection in collections
            for rule in collection["rules"]
            if rule["name"] == "authenticode-and-tls-revocation"
        )
        self.assertEqual(certificate_rule["targetFqdns"], "[variables('certificateFqdns')]")
        self.assertEqual(certificate_rule["sourceAddresses"], ["[parameters('windowsPrefix')]"])
        self.assertEqual(
            certificate_rule["protocols"],
            [{"protocolType": "Http", "port": 80}, {"protocolType": "Https", "port": 443}],
        )

    def test_all_dependent_services_are_private_from_creation(self):
        expected = {
            "Microsoft.Storage/storageAccounts": 2,
            "Microsoft.DocumentDB/databaseAccounts": 1,
            "Microsoft.Search/searchServices": 1,
        }
        for resource_type, count in expected.items():
            services = declarations(self.services, resource_type)
            self.assertEqual(len(services), count)
            for service in services:
                self.assertEqual(service["properties"]["publicNetworkAccess"].lower(), "disabled")
                self.assertIn("tags", service)
        cosmos = only(self.services, "Microsoft.DocumentDB/databaseAccounts")["properties"]
        self.assertTrue(cosmos["disableLocalAuth"])
        self.assertEqual(cosmos["networkAclBypass"], "None")
        search = only(self.services, "Microsoft.Search/searchServices")
        self.assertEqual(search["sku"]["name"], "basic")
        self.assertTrue(search["properties"]["disableLocalAuth"])
        self.assertEqual(search["properties"]["networkRuleSet"]["bypass"], "None")

    def test_document_and_agent_storage_are_distinct_and_keyless(self):
        for storage in declarations(self.services, "Microsoft.Storage/storageAccounts"):
            props = storage["properties"]
            self.assertFalse(props["allowBlobPublicAccess"])
            self.assertFalse(props["allowSharedKeyAccess"])
            self.assertTrue(props["supportsHttpsTrafficOnly"])
            self.assertEqual(props["networkAcls"]["bypass"], "None")
            self.assertEqual(props["networkAcls"]["defaultAction"], "Deny")
        container = only(self.services, "Microsoft.Storage/storageAccounts/blobServices/containers")
        self.assertIn("'documents'", container["name"])
        self.assertEqual(container["properties"]["publicAccess"], "None")
        self.assertIn("documentStorageName", container["name"])
        self.assertNotEqual(
            self.resources["variables"]["names"]["documents"],
            self.resources["variables"]["names"]["agentStorage"],
        )

    def test_foundry_injection_is_part_of_the_account_create(self):
        account = only(child(self.resources, "foundry-account"), "Microsoft.CognitiveServices/accounts")
        props = account["properties"]
        self.assertEqual(account["kind"], "AIServices")
        self.assertTrue(props["allowProjectManagement"])
        self.assertTrue(props["disableLocalAuth"])
        self.assertEqual(props["publicNetworkAccess"], "Disabled")
        self.assertEqual(props["networkAcls"]["bypass"], "None")
        injection = props["networkInjections"][0]
        self.assertEqual(injection["scenario"], "agent")
        self.assertEqual(injection["useMicrosoftManagedNetwork"], "[equals(parameters('networkMode'), 'managed')]")
        self.assertIn("parameters('agentSubnetId'), ''", injection["subnetArmId"])

    def test_private_ingress_is_present_in_both_modes_with_all_dns_zones(self):
        self.assertNotIn("condition", deployment(self.resources, "private-links-and-dns"))
        self.assertEqual(len(self.links["variables"]["zoneNames"]), 6)
        targets = self.links["variables"]["targets"]
        self.assertEqual(len(targets), 5)
        foundry = next(item for item in targets if item["groupId"] == "account")
        self.assertEqual(len(foundry["dnsZoneIds"]), 3)
        self.assertEqual(sum(item["groupId"] == "blob" for item in targets), 2)
        zone_groups = only(self.links, "Microsoft.Network/privateEndpoints/privateDnsZoneGroups")
        self.assertIn("dnsZones", zone_groups["dependsOn"])

    def test_only_managed_mode_creates_the_managed_network(self):
        module = deployment(self.resources, "foundry-managed-network")
        self.assertEqual(module["condition"], "[equals(parameters('networkMode'), 'managed')]")
        settings = only(self.managed, "Microsoft.CognitiveServices/accounts/managedNetworks")["properties"]["managedNetwork"]
        self.assertEqual(settings["isolationMode"], "AllowOnlyApprovedOutbound")
        self.assertEqual(settings["managedNetworkKind"], "V2")
        self.assertEqual(settings["firewallSku"], "Basic")
        self.assertTrue(settings["provisionNetworkNow"])

    def test_managed_network_has_self_documents_and_all_backing_endpoints(self):
        targets = self.managed["variables"]["privateTargets"]
        self.assertEqual(len(targets), 5)
        self.assertEqual(targets[0]["name"], "pe-foundry-self")
        self.assertEqual(targets[0]["groupId"], "account")
        self.assertIn("accountName", targets[0]["resourceId"])
        self.assertEqual({t["groupId"] for t in targets}, {"account", "blob", "Sql", "searchService"})
        self.assertIn("documentStorageName", targets[1]["resourceId"])
        self.assertIn("agentStorageName", targets[2]["resourceId"])

    def test_managed_network_approvals_are_target_resource_scoped(self):
        approvals = declarations(self.managed, "Microsoft.Authorization/roleAssignments")
        self.assertEqual(len(approvals), 5)
        for approval in approvals:
            self.assertEqual(approval["properties"]["principalId"], "[parameters('accountPrincipalId')]")
            self.assertIn("resourceId('Microsoft.", approval["scope"])
            self.assertNotIn("resourceGroups", approval["scope"])
        network = only(self.managed, "Microsoft.CognitiveServices/accounts/managedNetworks")
        self.assertEqual(len(network["dependsOn"]), 5)

    def test_managed_outbound_rules_are_serialized_and_build_dependencies_match(self):
        rules = declarations(self.managed, "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules")
        for rule in rules:
            if "copy" in rule:
                self.assertEqual(rule["copy"]["mode"], "serial")
                self.assertEqual(rule["copy"]["batchSize"], 1)
        fqdn = next(item for item in rules if item["properties"]["type"] == "FQDN")
        self.assertIn("entraRule", fqdn["dependsOn"])
        self.assertEqual(self.managed["variables"]["agentFqdns"], self.firewall["variables"]["agentFqdns"])
        self.assertIn("mcr.microsoft.com", self.managed["variables"]["agentFqdns"])
        self.assertIn("*.login.microsoft.com", self.managed["variables"]["agentFqdns"])
        self.assertIn("packagefeedproxy.microsoft.io", self.managed["variables"]["agentFqdns"])
        self.assertNotIn("github.com", self.managed["variables"]["agentFqdns"])
        self.assertIn("agentFqdns", fqdn["properties"]["destination"])
        collections = only(
            self.firewall, "Microsoft.Network/firewallPolicies/ruleCollectionGroups"
        )["properties"]["ruleCollections"]
        packages = next(
            rule
            for collection in collections
            for rule in collection["rules"]
            if rule["name"] == "approved-runtime-and-package-hosts"
        )
        self.assertEqual(packages["targetFqdns"], "[variables('agentFqdns')]")
        self.assertEqual(packages["protocols"], [{"protocolType": "Https", "port": 443}])
        self.assertEqual(packages["sourceAddresses"], "[variables('workloadPrefixes')]")
        self.assertEqual(
            self.firewall["variables"]["workloadPrefixes"],
            ["[parameters('windowsPrefix')]", "[parameters('agentPrefix')]"],
        )

    def test_standard_agent_connections_use_project_identity_not_keys(self):
        project = child(self.resources, "foundry-project-and-connections")
        self.assertEqual(only(project, "Microsoft.CognitiveServices/accounts/projects")["identity"]["type"], "SystemAssigned")
        connections = declarations(project, "Microsoft.CognitiveServices/accounts/projects/connections")
        self.assertEqual(len(connections), 3)
        self.assertEqual({c["properties"]["category"] for c in connections}, {"CosmosDB", "AzureStorageAccount", "CognitiveSearch"})
        for connection in connections:
            self.assertEqual(connection["properties"]["authType"], "AAD")
            self.assertNotIn("credentials", connection["properties"])
            self.assertNotIn("documentStorage", json.dumps(connection))
            self.assertIn("ResourceId", connection["properties"]["metadata"])

    def test_capability_host_and_rbac_provisioning_order(self):
        capability = deployment(self.resources, "project-capability-host")
        self.assertIn("agent-backing-provisioning-roles", json.dumps(capability["dependsOn"]))
        data = deployment(self.resources, "agent-backing-data-roles")
        self.assertIn("project-capability-host", json.dumps(data["dependsOn"]))
        project = deployment(self.resources, "foundry-project-and-connections")
        for dependency in ("private-links-and-dns", "foundry-managed-network", "model-deployments"):
            self.assertIn(dependency, json.dumps(project["dependsOn"]))
        for template in all_templates(self.root):
            self.assertEqual(declarations(template, "Microsoft.CognitiveServices/accounts/capabilityHosts"), [])
        host = only(child(self.resources, "project-capability-host"), "Microsoft.CognitiveServices/accounts/projects/capabilityHosts")
        self.assertEqual(set(host["properties"]), {"storageConnections", "threadStorageConnections", "vectorStoreConnections"})

    def test_project_model_proxy_and_standard_backing_roles_are_scoped(self):
        provisioning = child(self.resources, "agent-backing-provisioning-roles")
        roles = declarations(provisioning, "Microsoft.Authorization/roleAssignments")
        proxy = next(role for role in roles if "CognitiveServices/accounts" in role["scope"])
        self.assertIn("foundryUser", proxy["properties"]["roleDefinitionId"])
        for role in roles:
            self.assertEqual(role["properties"]["principalId"], "[parameters('projectPrincipalId')]")
            self.assertNotIn("documentStorage", json.dumps(role))
            self.assertIn("resourceId('Microsoft.", role["scope"])
        data = child(self.resources, "agent-backing-data-roles")
        cosmos = only(data, "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments")
        self.assertIn("sqlRoleDefinitions/00000000-0000-0000-0000-000000000002", cosmos["properties"]["roleDefinitionId"])

    def test_workspace_ids_are_read_from_rp_and_preserved_for_abac(self):
        project = child(self.resources, "foundry-project-and-connections")
        internal_id = project["outputs"]["internalId"]["value"]
        self.assertIn("reference(", internal_id)
        self.assertIn("'2025-04-01-preview').internalId", internal_id)
        self.assertNotIn("guid(", internal_id)
        data = child(self.resources, "agent-backing-data-roles")
        self.assertIn("projectInternalId", data["variables"]["compactId"])
        self.assertIn("*-azureml-agent", data["variables"]["ownerCondition"])
        role = only(data, "Microsoft.Authorization/roleAssignments")
        self.assertEqual(role["properties"]["conditionVersion"], "2.0")
        self.assertIn("workspaceId", role["name"])

    def test_client_permissions_and_future_agent_delegation_remain_narrow(self):
        roles = declarations(self.roles, "Microsoft.Authorization/roleAssignments")
        vm = [r for r in roles if r["properties"]["principalId"] == "[parameters('vmPrincipalId')]"]
        self.assertEqual(len(vm), 3)
        self.assertTrue(any("contentUnderstandingReader" in r["properties"]["roleDefinitionId"] for r in vm))
        self.assertTrue(any("foundryAgentConsumer" in r["properties"]["roleDefinitionId"] for r in vm))
        self.assertFalse(any("foundryUser" in r["properties"]["roleDefinitionId"] for r in vm))
        blob = next(r for r in vm if "storageBlobDataContributor" in r["properties"]["roleDefinitionId"])
        self.assertIn("blobServices/containers", blob["scope"])
        delegated = [r for r in roles if "condition" in r["properties"]]
        self.assertEqual(len(delegated), 2)
        for role in delegated:
            self.assertEqual(role["properties"]["principalId"], "[parameters('operatorPrincipalId')]")
            self.assertEqual(role["properties"]["conditionVersion"], "2.0")
        for variable in ("cuDelegationCondition", "blobDelegationCondition"):
            condition = self.roles["variables"][variable]
            self.assertIn("PrincipalType", condition)
            self.assertIn("ServicePrincipal", condition)
            self.assertIn("RoleDefinitionId", condition)
            self.assertIn("roleAssignments/write", condition)
            self.assertIn("roleAssignments/delete", condition)
        self.assertIn("contentUnderstandingReader", self.roles["variables"]["cuDelegationCondition"])
        self.assertIn("storageBlobDataReader", self.roles["variables"]["blobDelegationCondition"])

    def test_no_unapproved_tool_hosts_registries_or_public_document_telemetry(self):
        forbidden = {
            "Microsoft.ContainerRegistry/registries", "Microsoft.ApiManagement/service",
            "Microsoft.App/containerApps", "Microsoft.App/managedEnvironments",
            "Microsoft.Insights/components", "Microsoft.OperationalInsights/workspaces",
            "Microsoft.MachineLearningServices/workspaces", "Microsoft.Resources/deploymentScripts",
            "Microsoft.Authorization/roleDefinitions",
        }
        for template in all_templates(self.root):
            for resource in declarations(template):
                self.assertNotIn(resource["type"], forbidden)
        self.assertFalse(bindings(self.network, "virtual-network")["enableTelemetry"])
        self.assertFalse(bindings(self.network, "bastion")["enableTelemetry"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path, help="Real output from az bicep build")
    args, remaining = parser.parse_known_args()
    TEMPLATE_PATH = args.template
    if not TEMPLATE_PATH.is_file():
        parser.error("Compile infra\\main.bicep first and provide its --outfile path.")
    unittest.main(argv=[sys.argv[0], *remaining])
