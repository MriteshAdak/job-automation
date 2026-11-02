"""Generate Salesforce DX permission set files for SF-09."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PERMSETS_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "permissionsets"
FIELDS_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "objects" / "Run_Summary__c" / "fields"

server_managed_fields = {
    "Completion_Recorded_At__c",
    "First_Completed_At__c",
    "First_Status__c",
    "First_Headline__c",
    "First_Summary_Text__c",
    "Notification_Recipient__c",
    "Notification_Status__c",
    "Notification_Claim_Id__c",
    "Notification_Attempt_Count__c",
    "Notification_Last_Attempt_At__c",
    "Notification_Next_Attempt_At__c",
    "Notification_Receipt_Id__c",
    "Notification_Accepted_At__c",
    "Notification_Error_Code__c",
}

# Collect all field names
all_fields = sorted([p.name.replace(".field-meta.xml", "") for p in FIELDS_DIR.glob("*.field-meta.xml")])

# 1. Job_Summary_Worker
worker_lines = [
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
    "<PermissionSet xmlns=\"http://soap.sforce.com/2006/04/metadata\">",
    "    <description>Scoped permissions for the integration worker to upsert Run_Summary__c machine projection fields and read completion/notification state (SF-09).</description>",
    "    <hasActivationRequired>false</hasActivationRequired>",
    "    <label>Job Summary Worker</label>",
    "    <objectPermissions>",
    "        <allowCreate>true</allowCreate>",
    "        <allowDelete>false</allowDelete>",
    "        <allowEdit>true</allowEdit>",
    "        <allowRead>true</allowRead>",
    "        <modifyAllRecords>false</modifyAllRecords>",
    "        <object>Run_Summary__c</object>",
    "        <viewAllRecords>false</viewAllRecords>",
    "    </objectPermissions>",
]

for f in all_fields:
    editable = "false" if f in server_managed_fields else "true"
    worker_lines.extend([
        "    <fieldPermissions>",
        f"        <editable>{editable}</editable>",
        f"        <field>Run_Summary__c.{f}</field>",
        "        <readable>true</readable>",
        "    </fieldPermissions>",
    ])

worker_lines.append("</PermissionSet>")
(PERMSETS_DIR / "Job_Summary_Worker.permissionset-meta.xml").write_text("\n".join(worker_lines) + "\n", encoding="utf-8")
print("Wrote Job_Summary_Worker.permissionset-meta.xml")

# 2. Job_Summary_Reader
reader_lines = [
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
    "<PermissionSet xmlns=\"http://soap.sforce.com/2006/04/metadata\">",
    "    <description>Scoped permissions for the candidate user to view Run_Summary__c records and completion notifications (SF-09).</description>",
    "    <hasActivationRequired>false</hasActivationRequired>",
    "    <label>Job Summary Reader</label>",
    "    <objectPermissions>",
    "        <allowCreate>false</allowCreate>",
    "        <allowDelete>false</allowDelete>",
    "        <allowEdit>false</allowEdit>",
    "        <allowRead>true</allowRead>",
    "        <modifyAllRecords>false</modifyAllRecords>",
    "        <object>Run_Summary__c</object>",
    "        <viewAllRecords>false</viewAllRecords>",
    "    </objectPermissions>",
    "    <tabSettings>",
    "        <tab>Run_Summary__c</tab>",
    "        <visibility>Visible</visibility>",
    "    </tabSettings>",
]

for f in all_fields:
    reader_lines.extend([
        "    <fieldPermissions>",
        "        <editable>false</editable>",
        f"        <field>Run_Summary__c.{f}</field>",
        "        <readable>true</readable>",
        "    </fieldPermissions>",
    ])

reader_lines.append("</PermissionSet>")
(PERMSETS_DIR / "Job_Summary_Reader.permissionset-meta.xml").write_text("\n".join(reader_lines) + "\n", encoding="utf-8")
print("Wrote Job_Summary_Reader.permissionset-meta.xml")

# 3. Job_Summary_Administrator
admin_lines = [
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
    "<PermissionSet xmlns=\"http://soap.sforce.com/2006/04/metadata\">",
    "    <classAccesses>",
    "        <apexClass>JA_RunSummaryRecovery</apexClass>",
    "        <enabled>true</enabled>",
    "    </classAccesses>",
    "    <customPermissions>",
    "        <enabled>true</enabled>",
    "        <name>JA_Administer_Notifications</name>",
    "    </customPermissions>",
    "    <description>Scoped permissions for operator administration, retry, and reconciliation of Run_Summary__c notifications (SF-09).</description>",
    "    <hasActivationRequired>false</hasActivationRequired>",
    "    <label>Job Summary Administrator</label>",
    "    <objectPermissions>",
    "        <allowCreate>false</allowCreate>",
    "        <allowDelete>false</allowDelete>",
    "        <allowEdit>true</allowEdit>",
    "        <allowRead>true</allowRead>",
    "        <modifyAllRecords>false</modifyAllRecords>",
    "        <object>Run_Summary__c</object>",
    "        <viewAllRecords>false</viewAllRecords>",
    "    </objectPermissions>",
    "    <tabSettings>",
    "        <tab>Run_Summary__c</tab>",
    "        <visibility>Visible</visibility>",
    "    </tabSettings>",
]

for f in all_fields:
    editable = "true" if f in server_managed_fields else "false"
    admin_lines.extend([
        "    <fieldPermissions>",
        f"        <editable>{editable}</editable>",
        f"        <field>Run_Summary__c.{f}</field>",
        "        <readable>true</readable>",
        "    </fieldPermissions>",
    ])

admin_lines.append("</PermissionSet>")
(PERMSETS_DIR / "Job_Summary_Administrator.permissionset-meta.xml").write_text("\n".join(admin_lines) + "\n", encoding="utf-8")
print("Wrote Job_Summary_Administrator.permissionset-meta.xml")

