"""Generate Salesforce DX field metadata files for Run_Summary__c (SF-09)."""

from pathlib import Path
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
FIELDS_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "objects" / "Run_Summary__c" / "fields"
FIELDS_DIR.mkdir(parents=True, exist_ok=True)

def write_xml(filename: str, content: str) -> None:
    path = FIELDS_DIR / filename
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"Wrote {filename}")

# 1. Run_Id__c
write_xml("Run_Id__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Run_Id__c</fullName>
    <caseSensitive>false</caseSensitive>
    <description>Unique normalized lowercase UUID identifying the logical search run. Required External ID (SF-09).</description>
    <externalId>true</externalId>
    <inlineHelpText>Normalized run UUID.</inlineHelpText>
    <label>Run ID</label>
    <length>36</length>
    <required>true</required>
    <trackHistory>true</trackHistory>
    <type>Text</type>
    <unique>true</unique>
</CustomField>""")

# 2. Contract_Schema_Version__c
write_xml("Contract_Schema_Version__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Contract_Schema_Version__c</fullName>
    <description>C15 contract schema version (e.g. 1.0) governing the run summary (SF-09).</description>
    <externalId>false</externalId>
    <label>Contract Schema Version</label>
    <length>16</length>
    <required>false</required>
    <trackHistory>false</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 3. Mapping_Version__c
write_xml("Mapping_Version__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Mapping_Version__c</fullName>
    <description>Agreed projection mapping version (e.g. 1.0 or 1.1) for summary delivery (SF-09).</description>
    <externalId>false</externalId>
    <label>Mapping Version</label>
    <length>16</length>
    <required>false</required>
    <trackHistory>false</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 4. Start_Time__c
write_xml("Start_Time__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Start_Time__c</fullName>
    <description>UTC timestamp when the pipeline run started (SF-09).</description>
    <externalId>false</externalId>
    <label>Start Time</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>DateTime</type>
</CustomField>""")

# 5. End_Time__c
write_xml("End_Time__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>End_Time__c</fullName>
    <description>UTC timestamp when the pipeline run ended (SF-09).</description>
    <externalId>false</externalId>
    <label>End Time</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>DateTime</type>
</CustomField>""")

# 6. Duration_Seconds__c
write_xml("Duration_Seconds__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Duration_Seconds__c</fullName>
    <description>Total elapsed execution duration in seconds with millisecond precision (SF-09).</description>
    <externalId>false</externalId>
    <label>Duration (Seconds)</label>
    <precision>18</precision>
    <required>false</required>
    <scale>3</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 7. Pipeline_Status__c
write_xml("Pipeline_Status__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Pipeline_Status__c</fullName>
    <description>Authoritative terminal outcome of the search run: success, partial, or failed (SF-09).</description>
    <externalId>false</externalId>
    <label>Pipeline Status</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Picklist</type>
    <valueSet>
        <restricted>true</restricted>
        <valueSetDefinition>
            <sorted>false</sorted>
            <value>
                <fullName>success</fullName>
                <default>false</default>
                <label>success</label>
            </value>
            <value>
                <fullName>partial</fullName>
                <default>false</default>
                <label>partial</label>
            </value>
            <value>
                <fullName>failed</fullName>
                <default>false</default>
                <label>failed</label>
            </value>
        </valueSetDefinition>
    </valueSet>
</CustomField>""")

# 8. Headline__c
write_xml("Headline__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Headline__c</fullName>
    <description>Human-readable sanitized headline describing the run outcome (SF-09).</description>
    <externalId>false</externalId>
    <label>Headline</label>
    <length>255</length>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 9. Summary_Text__c
write_xml("Summary_Text__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Summary_Text__c</fullName>
    <description>Plain text sanitized narrative summary bounded to 2,000 characters (SF-09).</description>
    <externalId>false</externalId>
    <label>Summary Text</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>4</visibleLines>
</CustomField>""")

# 10. Source_Postings_Count__c
write_xml("Source_Postings_Count__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Source_Postings_Count__c</fullName>
    <description>Total observed source postings across all sources, distinct from unique canonical jobs (SF-09).</description>
    <externalId>false</externalId>
    <label>Source Postings Count</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 11. Canonical_Jobs_New__c
write_xml("Canonical_Jobs_New__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Canonical_Jobs_New__c</fullName>
    <description>Count of newly discovered canonical job vacancies created during this run (SF-09).</description>
    <externalId>false</externalId>
    <label>Canonical Jobs New</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 12. Canonical_Jobs_Updated__c
write_xml("Canonical_Jobs_Updated__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Canonical_Jobs_Updated__c</fullName>
    <description>Count of existing canonical job vacancies updated with new revisions during this run (SF-09).</description>
    <externalId>false</externalId>
    <label>Canonical Jobs Updated</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 13. Canonical_Jobs_Duplicate__c
write_xml("Canonical_Jobs_Duplicate__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Canonical_Jobs_Duplicate__c</fullName>
    <description>Count of duplicate posting observations matched to known canonical jobs (SF-09).</description>
    <externalId>false</externalId>
    <label>Duplicate observations</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 14. Eligible_Count__c
write_xml("Eligible_Count__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Eligible_Count__c</fullName>
    <description>Canonical jobs evaluated with Eligible disposition under RUN-01 evaluation semantics (SF-09).</description>
    <externalId>false</externalId>
    <label>Eligible Count</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 15. Review_Count__c
write_xml("Review_Count__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Review_Count__c</fullName>
    <description>Canonical jobs evaluated with Review disposition requiring human attention (SF-09).</description>
    <externalId>false</externalId>
    <label>Review Count</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 16. Rejected_Count__c
write_xml("Rejected_Count__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Rejected_Count__c</fullName>
    <description>Canonical jobs evaluated with Rejected disposition failing criteria (SF-09).</description>
    <externalId>false</externalId>
    <label>Rejected Count</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 17. Sync_Succeeded__c
write_xml("Sync_Succeeded__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Sync_Succeeded__c</fullName>
    <description>Logical C12 job synchronization operations successfully published to Salesforce (SF-09).</description>
    <externalId>false</externalId>
    <label>Sync Succeeded</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 18. Sync_Failed__c
write_xml("Sync_Failed__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Sync_Failed__c</fullName>
    <description>Logical C12 job synchronization operations that failed during publication (SF-09).</description>
    <externalId>false</externalId>
    <label>Sync Failed</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 19. Quarantined_Count__c
write_xml("Quarantined_Count__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Quarantined_Count__c</fullName>
    <description>Count of malformed or schema-invalid raw source records held in quarantine (SF-09).</description>
    <externalId>false</externalId>
    <label>Quarantined Count</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 20. Sources_Attempted__c
write_xml("Sources_Attempted__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Sources_Attempted__c</fullName>
    <description>Comma-separated bounded list of safe source keys attempted during this run (SF-09).</description>
    <externalId>false</externalId>
    <label>Sources Attempted</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>3</visibleLines>
</CustomField>""")

# 21. Sources_Succeeded__c
write_xml("Sources_Succeeded__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Sources_Succeeded__c</fullName>
    <description>Comma-separated bounded list of safe source keys successfully retrieved (SF-09).</description>
    <externalId>false</externalId>
    <label>Sources Succeeded</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>3</visibleLines>
</CustomField>""")

# 22. Sources_Failed__c
write_xml("Sources_Failed__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Sources_Failed__c</fullName>
    <description>Comma-separated bounded list of safe source keys that encountered failures (SF-09).</description>
    <externalId>false</externalId>
    <label>Sources Failed</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>3</visibleLines>
</CustomField>""")

# 23. Source_Counts__c
write_xml("Source_Counts__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Source_Counts__c</fullName>
    <description>Bounded structured text (JSON/key-value) mapping source keys to observed posting counts (SF-09).</description>
    <externalId>false</externalId>
    <label>Source Counts</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>3</visibleLines>
</CustomField>""")

# 24. Stage_Counts__c
write_xml("Stage_Counts__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Stage_Counts__c</fullName>
    <description>Bounded structured text recording pipeline stage keys, counts, units, and coverage status (SF-09).</description>
    <externalId>false</externalId>
    <label>Stage Counts</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>3</visibleLines>
</CustomField>""")

# 25. Coverage_Status__c
write_xml("Coverage_Status__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Coverage_Status__c</fullName>
    <description>Configured-scope source coverage status: complete, partial, or unavailable (SF-09).</description>
    <externalId>false</externalId>
    <label>Coverage Status</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Picklist</type>
    <valueSet>
        <restricted>true</restricted>
        <valueSetDefinition>
            <sorted>false</sorted>
            <value>
                <fullName>complete</fullName>
                <default>false</default>
                <label>complete</label>
            </value>
            <value>
                <fullName>partial</fullName>
                <default>false</default>
                <label>partial</label>
            </value>
            <value>
                <fullName>unavailable</fullName>
                <default>false</default>
                <label>unavailable</label>
            </value>
        </valueSetDefinition>
    </valueSet>
</CustomField>""")

# 26. Projection_Truncated__c
write_xml("Projection_Truncated__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Projection_Truncated__c</fullName>
    <defaultValue>false</defaultValue>
    <description>Indicates whether long lists or structured text were safely truncated to stay within storage bounds (SF-09).</description>
    <externalId>false</externalId>
    <label>Projection Truncated</label>
    <trackHistory>false</trackHistory>
    <type>Checkbox</type>
</CustomField>""")

# 27. Error_Summary__c
write_xml("Error_Summary__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Error_Summary__c</fullName>
    <description>Sanitized plain text error summary bounded to 500 characters. Nullable to clear on recovery (SF-09).</description>
    <externalId>false</externalId>
    <label>Error Summary</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>3</visibleLines>
</CustomField>""")

# 28. Pending_Work_Summary__c
write_xml("Pending_Work_Summary__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Pending_Work_Summary__c</fullName>
    <description>Sanitized plain text pending work summary bounded to 500 characters (SF-09).</description>
    <externalId>false</externalId>
    <label>Pending Work Summary</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>3</visibleLines>
</CustomField>""")

# 29. Revision__c
write_xml("Revision__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Revision__c</fullName>
    <description>Positive monotonic revision sequence counter governing summary updates (SF-09).</description>
    <externalId>false</externalId>
    <label>Revision</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>true</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 30. Payload_Hash__c
write_xml("Payload_Hash__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Payload_Hash__c</fullName>
    <description>Canonical SHA-256 fingerprint over all delivery-owned mutable fields of this revision (SF-09).</description>
    <externalId>false</externalId>
    <label>Payload Hash</label>
    <length>64</length>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 31. First_Completion_Key__c
write_xml("First_Completion_Key__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>First_Completion_Key__c</fullName>
    <caseSensitive>false</caseSensitive>
    <description>Canonical verified org ID + ':' + run UUID key granting exactly one completion entitlement (SF-09).</description>
    <externalId>true</externalId>
    <label>First Completion Key</label>
    <length>80</length>
    <required>true</required>
    <trackHistory>true</trackHistory>
    <type>Text</type>
    <unique>true</unique>
</CustomField>""")

# 32. First_Payload_Hash__c
write_xml("First_Payload_Hash__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>First_Payload_Hash__c</fullName>
    <description>Immutable SHA-256 fingerprint of the initial terminal completion payload (SF-09).</description>
    <externalId>false</externalId>
    <label>First Payload Hash</label>
    <length>64</length>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 33. First_Completed_At__c
write_xml("First_Completed_At__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>First_Completed_At__c</fullName>
    <description>Immutable UTC timestamp when the first terminal outcome was completed (SF-09).</description>
    <externalId>false</externalId>
    <label>First Completed At</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>DateTime</type>
</CustomField>""")

# 34. First_Status__c
write_xml("First_Status__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>First_Status__c</fullName>
    <description>Immutable terminal status snapshot captured on initial completion (SF-09).</description>
    <externalId>false</externalId>
    <label>First Status</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Picklist</type>
    <valueSet>
        <restricted>true</restricted>
        <valueSetDefinition>
            <sorted>false</sorted>
            <value>
                <fullName>success</fullName>
                <default>false</default>
                <label>success</label>
            </value>
            <value>
                <fullName>partial</fullName>
                <default>false</default>
                <label>partial</label>
            </value>
            <value>
                <fullName>failed</fullName>
                <default>false</default>
                <label>failed</label>
            </value>
        </valueSetDefinition>
    </valueSet>
</CustomField>""")

# 35. First_Headline__c
write_xml("First_Headline__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>First_Headline__c</fullName>
    <description>Immutable headline snapshot captured on initial completion (SF-09).</description>
    <externalId>false</externalId>
    <label>First Headline</label>
    <length>255</length>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 36. First_Summary_Text__c
write_xml("First_Summary_Text__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>First_Summary_Text__c</fullName>
    <description>Immutable summary text snapshot captured on initial completion (SF-09).</description>
    <externalId>false</externalId>
    <label>First Summary Text</label>
    <length>32768</length>
    <type>LongTextArea</type>
    <visibleLines>4</visibleLines>
</CustomField>""")

# 37. Completion_Recorded_At__c
write_xml("Completion_Recorded_At__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Completion_Recorded_At__c</fullName>
    <description>Salesforce server timestamp when the first terminal outcome was admitted into Salesforce (SF-09).</description>
    <externalId>false</externalId>
    <label>Completion Recorded At</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>DateTime</type>
</CustomField>""")

# 38. Notification_Recipient__c
write_xml("Notification_Recipient__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Recipient__c</fullName>
    <deleteConstraint>SetNull</deleteConstraint>
    <description>Configured candidate User lookup resolved at notification admission (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Recipient</label>
    <referenceTo>User</referenceTo>
    <relationshipLabel>Run Summaries</relationshipLabel>
    <relationshipName>Run_Summaries</relationshipName>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Lookup</type>
</CustomField>""")

# 39. Notification_Status__c
write_xml("Notification_Status__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Status__c</fullName>
    <description>Server-managed notification delivery lifecycle status (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Status</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Picklist</type>
    <valueSet>
        <restricted>true</restricted>
        <valueSetDefinition>
            <sorted>false</sorted>
            <value>
                <fullName>none</fullName>
                <default>true</default>
                <label>none</label>
            </value>
            <value>
                <fullName>pending</fullName>
                <default>false</default>
                <label>pending</label>
            </value>
            <value>
                <fullName>dispatching</fullName>
                <default>false</default>
                <label>dispatching</label>
            </value>
            <value>
                <fullName>confirmed</fullName>
                <default>false</default>
                <label>confirmed</label>
            </value>
            <value>
                <fullName>failed</fullName>
                <default>false</default>
                <label>failed</label>
            </value>
            <value>
                <fullName>unknown</fullName>
                <default>false</default>
                <label>unknown</label>
            </value>
            <value>
                <fullName>suppressed</fullName>
                <default>false</default>
                <label>suppressed</label>
            </value>
        </valueSetDefinition>
    </valueSet>
</CustomField>""")

# 40. Notification_Claim_Id__c
write_xml("Notification_Claim_Id__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Claim_Id__c</fullName>
    <description>Unique server-owned dispatch attempt claim token providing pre-send mutual exclusion (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Claim ID</label>
    <length>80</length>
    <required>false</required>
    <trackHistory>false</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 41. Notification_Attempt_Count__c
write_xml("Notification_Attempt_Count__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Attempt_Count__c</fullName>
    <description>Count of notification dispatch attempts executed for this completion entitlement (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Attempt Count</label>
    <precision>18</precision>
    <required>false</required>
    <scale>0</scale>
    <trackHistory>false</trackHistory>
    <type>Number</type>
    <unique>false</unique>
</CustomField>""")

# 42. Notification_Last_Attempt_At__c
write_xml("Notification_Last_Attempt_At__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Last_Attempt_At__c</fullName>
    <description>UTC timestamp of the most recent notification dispatch attempt (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Last Attempt At</label>
    <required>false</required>
    <trackHistory>false</trackHistory>
    <type>DateTime</type>
</CustomField>""")

# 43. Notification_Next_Attempt_At__c
write_xml("Notification_Next_Attempt_At__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Next_Attempt_At__c</fullName>
    <description>Earliest scheduled retry timestamp for pre-send failures in retry_wait state (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Next Attempt At</label>
    <required>false</required>
    <trackHistory>false</trackHistory>
    <type>DateTime</type>
</CustomField>""")

# 44. Notification_Receipt_Id__c
write_xml("Notification_Receipt_Id__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Receipt_Id__c</fullName>
    <description>Platform notification delivery confirmation receipt identifier, immutable once confirmed (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Receipt ID</label>
    <length>80</length>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 45. Notification_Accepted_At__c
write_xml("Notification_Accepted_At__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Accepted_At__c</fullName>
    <description>UTC timestamp when the platform notification delivery was confirmed (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Accepted At</label>
    <required>false</required>
    <trackHistory>true</trackHistory>
    <type>DateTime</type>
</CustomField>""")

# 46. Notification_Error_Code__c
write_xml("Notification_Error_Code__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Notification_Error_Code__c</fullName>
    <description>Allowlisted safe error code identifying the cause of dispatch failure or uncertainty (SF-09).</description>
    <externalId>false</externalId>
    <label>Notification Error Code</label>
    <length>80</length>
    <required>false</required>
    <trackHistory>false</trackHistory>
    <type>Text</type>
    <unique>false</unique>
</CustomField>""")

# 47. Is_First_Completion__c
write_xml("Is_First_Completion__c.field-meta.xml", """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Is_First_Completion__c</fullName>
    <defaultValue>false</defaultValue>
    <description>Optional client compatibility hint indicating first completion intent; server admission remains authoritative (SF-09).</description>
    <externalId>false</externalId>
    <label>Is First Completion</label>
    <trackHistory>false</trackHistory>
    <type>Checkbox</type>
</CustomField>""")

print("All 47 fields generated successfully.")

