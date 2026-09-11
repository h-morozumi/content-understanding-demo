// Built-in role GUIDs, not identities or subscription IDs.
// Foundry role names changed in 2026; their GUIDs are unchanged.
// https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning
// New CU role GUIDs are also published by Microsoft in:
// https://github.com/Azure/Azure-Sentinel/blob/master/Sample%20Data/Feeds/AzureBuiltInRole.csv
// https://github.com/microsoft/fsi-agentic-wealth-transfer/blob/main/infra/resources.bicep
@export()
var roleIds = {
  foundryAgentConsumer: 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6'
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  foundryProjectManager: 'eadc314b-1a2d-4efa-be10-5d325db5065e'
  contentUnderstandingReader: '379c52cb-64de-498c-8b5b-c6170d6c49d4'
  contentUnderstandingContributor: '59a2dba3-6303-4fd8-9a2e-8cbb4bdda972'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  cosmosOperator: '230815da-be43-4aae-9cb4-875f7bd000aa'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  networkConnectionApprover: 'b556d68e-0be0-4f35-a333-ad7ee1ce17ea'
  roleBasedAccessControlAdministrator: 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
}
