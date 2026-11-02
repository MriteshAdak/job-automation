"""Generate salesforce/manifest/sf09.xml and update package.xml and metadata-ownership.json for SF-09."""

import json
from pathlib import Path
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"
OWNERSHIP_FILE = REPO_ROOT / "salesforce" / "metadata-ownership.json"
FIELDS_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "objects" / "Run_Summary__c" / "fields"
RULES_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "objects" / "Run_Summary__c" / "validationRules"

all_fields = sorted([f"Run_Summary__c.{p.name.replace('.field-meta.xml', '')}" for p in FIELDS_DIR.glob("*.field-meta.xml")])
all_rules = sorted([f"Run_Summary__c.{p.name.replace('.validationRule-meta.xml', '')}" for p in RULES_DIR.glob("*.validationRule-meta.xml")])

sf09_types = [
    {
        "name": "CustomNotificationType",
        "members": ["JA_Run_Completed"],
    },
    {
        "name": "CustomObject",
        "members": ["Run_Summary__c"],
    },
    {
        "name": "CustomField",
        "members": all_fields,
    },
    {
        "name": "ValidationRule",
        "members": all_rules,
    },
    {
        "name": "ListView",
        "members": [
            "Run_Summary__c.All_Run_Summaries",
            "Run_Summary__c.Failed_Or_Partial_Runs",
            "Run_Summary__c.Unresolved_Notifications",
        ],
    },
    {
        "name": "CustomTab",
        "members": ["Run_Summary__c"],
    },
    {
        "name": "Layout",
        "members": ["Run_Summary__c-Run Summary Layout"],
    },
    {
        "name": "Flow",
        "members": ["JA_Run_Summary_Completion"],
    },
    {
        "name": "ApexClass",
        "members": [
            "JA_RunSummaryGuard",
            "JA_RunSummaryGuardTest",
            "JA_RunSummaryDispatcher",
            "JA_RunSummaryDispatcherTest",
            "JA_RunSummaryRecovery",
            "JA_RunSummaryRecoveryTest",
        ],
    },
    {
        "name": "PermissionSet",
        "members": [
            "Job_Summary_Worker",
            "Job_Summary_Reader",
            "Job_Summary_Administrator",
        ],
    },
]

# 1. Build sf09.xml
lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<Package xmlns="http://soap.sforce.com/2006/04/metadata">',
]
for t in sf09_types:
    lines.append('    <types>')
    for m in t["members"]:
        lines.append(f'        <members>{m}</members>')
    lines.append(f'        <name>{t["name"]}</name>')
    lines.append('    </types>')
lines.append('    <version>60.0</version>')
lines.append('</Package>')

(MANIFEST_DIR / "sf09.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Wrote salesforce/manifest/sf09.xml")

# 2. Update metadata-ownership.json
with open(OWNERSHIP_FILE, "r", encoding="utf-8") as f:
    ownership = json.load(f)

po = ownership["project_owned"]
if "Run_Summary__c" not in po.setdefault("CustomObject", []):
    po["CustomObject"].append("Run_Summary__c")

for fld in all_fields:
    if fld not in po.setdefault("CustomField", []):
        po["CustomField"].append(fld)

for rule in all_rules:
    if rule not in po.setdefault("ValidationRule", []):
        po["ValidationRule"].append(rule)

for lview in ["Run_Summary__c.All_Run_Summaries", "Run_Summary__c.Failed_Or_Partial_Runs", "Run_Summary__c.Unresolved_Notifications"]:
    if lview not in po.setdefault("ListView", []):
        po["ListView"].append(lview)

if "Run_Summary__c" not in po.setdefault("CustomTab", []):
    po["CustomTab"].append("Run_Summary__c")

if "Run_Summary__c-Run Summary Layout" not in po.setdefault("Layout", []):
    po["Layout"].append("Run_Summary__c-Run Summary Layout")

if "JA_Run_Completed" not in po.setdefault("CustomNotificationType", []):
    po["CustomNotificationType"].append("JA_Run_Completed")

if "JA_Run_Summary_Completion" not in po.setdefault("Flow", []):
    po["Flow"].append("JA_Run_Summary_Completion")

for cls in ["JA_RunSummaryGuard", "JA_RunSummaryGuardTest", "JA_RunSummaryDispatcher", "JA_RunSummaryDispatcherTest", "JA_RunSummaryRecovery", "JA_RunSummaryRecoveryTest"]:
    if cls not in po.setdefault("ApexClass", []):
        po["ApexClass"].append(cls)

for ps in ["Job_Summary_Worker", "Job_Summary_Reader", "Job_Summary_Administrator"]:
    if ps not in po.setdefault("PermissionSet", []):
        po["PermissionSet"].append(ps)

with open(OWNERSHIP_FILE, "w", encoding="utf-8") as f:
    json.dump(ownership, f, indent=2)
print("Updated salesforce/metadata-ownership.json")

# 3. Update package.xml
pkg_file = MANIFEST_DIR / "package.xml"
tree = ET.parse(pkg_file)
root = tree.getroot()
ns = {"ns": "http://soap.sforce.com/2006/04/metadata"}
ET.register_namespace("", "http://soap.sforce.com/2006/04/metadata")

type_elements = {elem.find("ns:name", ns).text: elem for elem in root.findall("ns:types", ns) if elem.find("ns:name", ns) is not None}

for t in sf09_types:
    tname = t["name"]
    elem = type_elements.get(tname)
    if elem is None:
        elem = ET.SubElement(root, "types")
        name_elem = ET.SubElement(elem, "name")
        name_elem.text = tname
        type_elements[tname] = elem

    existing_members = {m.text for m in elem.findall("ns:members", ns)}
    # Insert members before <name>
    name_sub = elem.find("ns:name", ns)
    for m in t["members"]:
        if m not in existing_members:
            m_elem = ET.Element("{http://soap.sforce.com/2006/04/metadata}members")
            m_elem.text = m
            # Insert before name element
            idx = list(elem).index(name_sub) if name_sub in list(elem) else len(list(elem))
            elem.insert(idx, m_elem)

tree.write(pkg_file, encoding="utf-8", xml_declaration=True)
print("Updated salesforce/manifest/package.xml")

