"""Salesforce metadata parser and schema compatibility validator (SF-01).

Parses Salesforce DX source metadata (CustomObjects, CustomFields, ValidationRules)
and validates compatibility against SyncMappingConfig and SF-01 contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from job_automation.salesforce.sync_settings import SyncMappingConfig

# XML namespace used in Salesforce metadata
SF_NS = "{http://soap.sforce.com/2006/04/metadata}"


def _tag_name(elem: ET.Element) -> str:
    """Strip XML namespace prefix from element tag."""
    tag = elem.tag
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_text(elem: ET.Element, name: str) -> str | None:
    """Find direct child element text regardless of namespace."""
    for child in elem:
        if _tag_name(child) == name:
            return child.text.strip() if child.text else ""
    return None


def _find_bool(elem: ET.Element, name: str, default: bool = False) -> bool:
    """Find boolean child element value."""
    txt = _find_text(elem, name)
    if txt is None:
        return default
    return txt.lower() in ("true", "1")


@dataclass(frozen=True)
class CustomFieldMetadata:
    """Parsed CustomField metadata attributes."""

    full_name: str
    label: str
    field_type: str
    required: bool = False
    unique: bool = False
    case_sensitive: bool = True
    external_id: bool = False
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    reference_to: str | None = None
    relationship_name: str | None = None
    delete_constraint: str | None = None
    picklist_values: tuple[str, ...] = ()
    default_picklist_value: str | None = None
    restricted_picklist: bool = False
    description: str | None = None
    inline_help_text: str | None = None


@dataclass(frozen=True)
class ValidationRuleMetadata:
    """Parsed ValidationRule metadata attributes."""

    full_name: str
    active: bool
    error_condition_formula: str
    error_message: str
    error_display_field: str | None = None
    description: str | None = None


@dataclass
class CustomObjectMetadata:
    """Parsed CustomObject metadata including custom fields and validation rules."""

    name: str
    label: str
    plural_label: str
    sharing_model: str
    name_field_type: str  # "Text" or "AutoNumber"
    name_field_label: str
    name_field_display_format: str | None = None
    description: str | None = None
    visibility: str | None = None
    fields: dict[str, CustomFieldMetadata] = field(default_factory=dict)
    validation_rules: dict[str, ValidationRuleMetadata] = field(default_factory=dict)


@dataclass(frozen=True)
class MetadataCompatibilityReport:
    """Report evaluating metadata compatibility against SyncMappingConfig."""

    compatible: bool
    issues: tuple[str, ...]
    warnings: tuple[str, ...]

    def raise_if_incompatible(self) -> None:
        if not self.compatible:
            issues_str = "\n - ".join(self.issues)
            raise ValueError(f"Salesforce metadata is incompatible with sync mapping:\n - {issues_str}")


def parse_custom_field_xml(content_or_path: str | Path) -> CustomFieldMetadata:
    """Parse a .field-meta.xml string or file path."""
    if isinstance(content_or_path, Path) or (isinstance(content_or_path, str) and "\n" not in content_or_path and Path(content_or_path).is_file()):
        tree = ET.parse(content_or_path)
        root = tree.getroot()
    else:
        root = ET.fromstring(content_or_path)

    full_name = _find_text(root, "fullName") or ""
    label = _find_text(root, "label") or full_name
    field_type = _find_text(root, "type") or "Text"
    required = _find_bool(root, "required", False)
    unique = _find_bool(root, "unique", False)
    case_sensitive = _find_bool(root, "caseSensitive", True)
    external_id = _find_bool(root, "externalId", False)

    length_str = _find_text(root, "length")
    length = int(length_str) if length_str and length_str.isdigit() else None

    prec_str = _find_text(root, "precision")
    precision = int(prec_str) if prec_str and prec_str.isdigit() else None

    scale_str = _find_text(root, "scale")
    scale = int(scale_str) if scale_str and scale_str.isdigit() else None

    reference_to = _find_text(root, "referenceTo")
    relationship_name = _find_text(root, "relationshipName")
    delete_constraint = _find_text(root, "deleteConstraint")
    description = _find_text(root, "description")
    inline_help_text = _find_text(root, "inlineHelpText")

    # Picklist value set parsing
    picklist_values: list[str] = []
    default_picklist_value: str | None = None
    restricted_picklist = False

    for child in root:
        if _tag_name(child) == "valueSet":
            restricted_picklist = _find_bool(child, "restricted", False)
            for vs_child in child:
                if _tag_name(vs_child) == "valueSetDefinition":
                    for v_elem in vs_child:
                        if _tag_name(v_elem) == "value":
                            val_name = _find_text(v_elem, "fullName") or ""
                            if val_name:
                                picklist_values.append(val_name)
                                if _find_bool(v_elem, "default", False):
                                    default_picklist_value = val_name

    return CustomFieldMetadata(
        full_name=full_name,
        label=label,
        field_type=field_type,
        required=required,
        unique=unique,
        case_sensitive=case_sensitive,
        external_id=external_id,
        length=length,
        precision=precision,
        scale=scale,
        reference_to=reference_to,
        relationship_name=relationship_name,
        delete_constraint=delete_constraint,
        picklist_values=tuple(picklist_values),
        default_picklist_value=default_picklist_value,
        restricted_picklist=restricted_picklist,
        description=description,
        inline_help_text=inline_help_text,
    )


def parse_validation_rule_xml(content_or_path: str | Path) -> ValidationRuleMetadata:
    """Parse a .validationRule-meta.xml string or file path."""
    if isinstance(content_or_path, Path) or (isinstance(content_or_path, str) and "\n" not in content_or_path and Path(content_or_path).is_file()):
        tree = ET.parse(content_or_path)
        root = tree.getroot()
    else:
        root = ET.fromstring(content_or_path)

    full_name = _find_text(root, "fullName") or ""
    active = _find_bool(root, "active", True)
    formula = _find_text(root, "errorConditionFormula") or ""
    msg = _find_text(root, "errorMessage") or ""
    display_field = _find_text(root, "errorDisplayField")
    description = _find_text(root, "description")

    return ValidationRuleMetadata(
        full_name=full_name,
        active=active,
        error_condition_formula=formula,
        error_message=msg,
        error_display_field=display_field,
        description=description,
    )


def parse_custom_object_dir(obj_dir: Path) -> CustomObjectMetadata:
    """Parse a Salesforce DX custom object directory (e.g. objects/Job__c/)."""
    obj_name = obj_dir.name
    meta_xml_path = obj_dir / f"{obj_name}.object-meta.xml"

    if meta_xml_path.is_file():
        tree = ET.parse(meta_xml_path)
        root = tree.getroot()
        label = _find_text(root, "label") or obj_name
        plural_label = _find_text(root, "pluralLabel") or label
        sharing_model = _find_text(root, "sharingModel") or "ReadWrite"
        description = _find_text(root, "description")
        visibility = _find_text(root, "visibility")

        name_field_type = "Text"
        name_field_label = "Name"
        name_field_display_format = None
        for child in root:
            if _tag_name(child) == "nameField":
                name_field_type = _find_text(child, "type") or "Text"
                name_field_label = _find_text(child, "label") or "Name"
                name_field_display_format = _find_text(child, "displayFormat")
    else:
        label = obj_name
        plural_label = obj_name
        sharing_model = "ReadWrite"
        description = None
        visibility = None
        name_field_type = "Text"
        name_field_label = "Name"
        name_field_display_format = None

    fields: dict[str, CustomFieldMetadata] = {}
    fields_dir = obj_dir / "fields"
    if fields_dir.is_dir():
        for f_path in fields_dir.glob("*.field-meta.xml"):
            f_meta = parse_custom_field_xml(f_path)
            fn = f_meta.full_name or f_path.name.replace(".field-meta.xml", "")
            fields[fn.lower()] = f_meta

    validation_rules: dict[str, ValidationRuleMetadata] = {}
    val_dir = obj_dir / "validationRules"
    if val_dir.is_dir():
        for v_path in val_dir.glob("*.validationRule-meta.xml"):
            v_meta = parse_validation_rule_xml(v_path)
            vn = v_meta.full_name or v_path.name.replace(".validationRule-meta.xml", "")
            validation_rules[vn.lower()] = v_meta

    return CustomObjectMetadata(
        name=obj_name,
        label=label,
        plural_label=plural_label,
        sharing_model=sharing_model,
        name_field_type=name_field_type,
        name_field_label=name_field_label,
        name_field_display_format=name_field_display_format,
        description=description,
        visibility=visibility,
        fields=fields,
        validation_rules=validation_rules,
    )


def load_salesforce_dx_objects(objects_dir: Path | str) -> dict[str, CustomObjectMetadata]:
    """Load all custom objects from a Salesforce DX objects directory."""
    p = Path(objects_dir).resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"Objects directory not found: '{p}'")

    result: dict[str, CustomObjectMetadata] = {}
    for item in p.iterdir():
        if item.is_dir() and (item.name.endswith("__c") or item.name.endswith("__mdt")):
            obj = parse_custom_object_dir(item)
            result[obj.name.lower()] = obj
    return result


def validate_metadata_compatibility(
    objects: dict[str, CustomObjectMetadata],
    config: SyncMappingConfig,
) -> MetadataCompatibilityReport:
    """Validate that the given Salesforce metadata supports the SyncMappingConfig requirements."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Company Object Verification
    comp_obj_name = config.company_object.strip().lower()
    if comp_obj_name not in objects:
        issues.append(f"Company object '{config.company_object}' is missing from metadata.")
        return MetadataCompatibilityReport(compatible=False, issues=tuple(issues), warnings=tuple(warnings))

    comp_obj = objects[comp_obj_name]

    # Canonical Company External ID
    comp_ext_id = config.company_external_id_field.strip().lower()
    if comp_ext_id not in comp_obj.fields:
        issues.append(f"Field '{config.company_external_id_field}' is missing on '{config.company_object}'.")
    else:
        f = comp_obj.fields[comp_ext_id]
        if f.field_type != "Text":
            issues.append(f"Field '{config.company_external_id_field}' must be Text, got '{f.field_type}'.")
        if not f.external_id:
            issues.append(f"Field '{config.company_external_id_field}' must be an External ID.")
        if not f.unique:
            issues.append(f"Field '{config.company_external_id_field}' must be Unique.")
        if f.case_sensitive:
            issues.append(f"Field '{config.company_external_id_field}' must be case-insensitive unique (caseSensitive=false).")
        if f.length is not None and f.length < 36:
            issues.append(f"Field '{config.company_external_id_field}' length {f.length} is too short for UUID (minimum 36).")

    # Company Name Field
    comp_name_field = config.company_name_field.strip()
    if comp_name_field.lower() == "name":
        if comp_obj.name_field_type == "AutoNumber":
            issues.append(
                f"Company name field is mapped to standard 'Name', but '{config.company_object}.Name' is AutoNumber. Cannot write company name to an autonumber field."
            )
    else:
        if comp_name_field.lower() not in comp_obj.fields:
            issues.append(f"Custom company name field '{comp_name_field}' is missing on '{config.company_object}'.")
        else:
            f = comp_obj.fields[comp_name_field.lower()]
            if f.field_type != "Text":
                issues.append(f"Company name field '{comp_name_field}' must be Text, got '{f.field_type}'.")

    # Company Marker and Version
    comp_marker = config.sync_marker_field.strip().lower()
    if comp_marker not in comp_obj.fields:
        issues.append(f"Sync marker field '{config.sync_marker_field}' is missing on '{config.company_object}'.")

    comp_version = config.sync_version_field.strip().lower()
    if comp_version not in comp_obj.fields:
        issues.append(f"Sync version field '{config.sync_version_field}' is missing on '{config.company_object}'.")
    else:
        f = comp_obj.fields[comp_version]
        if f.field_type != "Number":
            issues.append(f"Sync version field '{config.sync_version_field}' on '{config.company_object}' must be Number, got '{f.field_type}'.")

    # 2. Job Object Verification
    job_obj_name = config.job_object.strip().lower()
    if job_obj_name not in objects:
        issues.append(f"Job object '{config.job_object}' is missing from metadata.")
        return MetadataCompatibilityReport(compatible=False, issues=tuple(issues), warnings=tuple(warnings))

    job_obj = objects[job_obj_name]

    # Canonical Job External ID
    job_ext_id = config.job_external_id_field.strip().lower()
    if job_ext_id not in job_obj.fields:
        issues.append(f"Field '{config.job_external_id_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[job_ext_id]
        if f.field_type != "Text":
            issues.append(f"Field '{config.job_external_id_field}' must be Text, got '{f.field_type}'.")
        if not f.external_id:
            issues.append(f"Field '{config.job_external_id_field}' must be an External ID.")
        if not f.unique:
            issues.append(f"Field '{config.job_external_id_field}' must be Unique.")
        if f.case_sensitive:
            issues.append(f"Field '{config.job_external_id_field}' must be case-insensitive unique (caseSensitive=false).")
        if f.length is not None and f.length < 36:
            issues.append(f"Field '{config.job_external_id_field}' length {f.length} is too short for UUID (minimum 36).")

    # Title Field
    title_field = config.title_field.strip()
    if title_field.lower() == "name":
        if job_obj.name_field_type == "AutoNumber":
            issues.append(
                f"Job title field is mapped to standard 'Name', but '{config.job_object}.Name' is AutoNumber. Cannot write job title to an autonumber field."
            )
    else:
        if title_field.lower() not in job_obj.fields:
            issues.append(f"Custom title field '{title_field}' is missing on '{config.job_object}'.")
        else:
            f = job_obj.fields[title_field.lower()]
            if f.field_type != "Text":
                issues.append(f"Job title field '{title_field}' must be Text, got '{f.field_type}'.")

    # Company Lookup Field
    lookup_field = config.job_company_lookup_field.strip().lower()
    if lookup_field not in job_obj.fields:
        issues.append(f"Lookup field '{config.job_company_lookup_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[lookup_field]
        if f.field_type != "Lookup":
            issues.append(f"Field '{config.job_company_lookup_field}' must be a Lookup, got '{f.field_type}'.")
        if f.reference_to and f.reference_to.strip().lower() != comp_obj_name:
            issues.append(
                f"Lookup field '{config.job_company_lookup_field}' references '{f.reference_to}', but expected '{config.company_object}'."
            )
        if f.delete_constraint and f.delete_constraint not in ("Restrict", "SetNull"):
            issues.append(
                f"Lookup field '{config.job_company_lookup_field}' deleteConstraint is '{f.delete_constraint}'; must be Restrict or SetNull (cascade delete is forbidden)."
            )

    # Availability Picklist Field
    avail_field = config.availability_field.strip().lower()
    if avail_field not in job_obj.fields:
        issues.append(f"Availability field '{config.availability_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[avail_field]
        if f.field_type != "Picklist":
            issues.append(f"Availability field '{config.availability_field}' must be Picklist, got '{f.field_type}'.")
        for local_val, sf_val in config.availability_mapping.items():
            if sf_val not in f.picklist_values:
                issues.append(
                    f"Availability picklist on '{config.job_object}' is missing mapped value '{sf_val}' (for local '{local_val}')."
                )
        if f.default_picklist_value:
            issues.append(
                f"Availability picklist on '{config.job_object}' has default value '{f.default_picklist_value}'. Availability must not default automatically."
            )

    # Disposition Picklist Field
    disp_field = config.disposition_field.strip().lower()
    if disp_field not in job_obj.fields:
        issues.append(f"Disposition field '{config.disposition_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[disp_field]
        if f.field_type != "Picklist":
            issues.append(f"Disposition field '{config.disposition_field}' must be Picklist, got '{f.field_type}'.")
        for local_val, sf_val in config.disposition_mapping.items():
            if sf_val not in f.picklist_values:
                issues.append(
                    f"Disposition picklist on '{config.job_object}' is missing mapped value '{sf_val}' (for local '{local_val}')."
                )
        if f.default_picklist_value:
            issues.append(
                f"Disposition picklist on '{config.job_object}' has default value '{f.default_picklist_value}'. Disposition must not default automatically."
            )

    # Reason Field
    reason_field = config.reason_field.strip().lower()
    if reason_field not in job_obj.fields:
        issues.append(f"Reason field '{config.reason_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[reason_field]
        if f.field_type not in ("LongTextArea", "Text"):
            issues.append(f"Reason field '{config.reason_field}' must be LongTextArea or Text, got '{f.field_type}'.")

    # Score and Scale Fields (Nullable)
    score_field = config.score_field.strip().lower()
    if score_field not in job_obj.fields:
        issues.append(f"Relevance score field '{config.score_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[score_field]
        if f.field_type != "Number":
            issues.append(f"Score field '{config.score_field}' must be Number, got '{f.field_type}'.")
        if f.required:
            issues.append(f"Score field '{config.score_field}' must be nullable (required=false) to allow rules-only null clearing.")

    scale_field = config.score_scale_field.strip().lower()
    if scale_field not in job_obj.fields:
        issues.append(f"Score scale field '{config.score_scale_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[scale_field]
        if f.field_type != "Text":
            issues.append(f"Score scale field '{config.score_scale_field}' must be Text, got '{f.field_type}'.")
        if f.required:
            issues.append(f"Score scale field '{config.score_scale_field}' must be nullable (required=false).")

    # Last Evaluated At (DateTime)
    eval_field = config.last_evaluated_field.strip().lower()
    if eval_field not in job_obj.fields:
        issues.append(f"Last evaluated field '{config.last_evaluated_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[eval_field]
        if f.field_type != "DateTime":
            issues.append(f"Last evaluated field '{config.last_evaluated_field}' must be DateTime, got '{f.field_type}'.")

    # Source URLs
    urls_field = config.source_urls_field.strip().lower()
    if urls_field not in job_obj.fields:
        issues.append(f"Source URLs field '{config.source_urls_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[urls_field]
        if f.field_type not in ("LongTextArea", "Text"):
            issues.append(f"Source URLs field '{config.source_urls_field}' must be LongTextArea or Text, got '{f.field_type}'.")

    # Job Marker and Version
    job_marker = config.sync_marker_field.strip().lower()
    if job_marker not in job_obj.fields:
        issues.append(f"Sync marker field '{config.sync_marker_field}' is missing on '{config.job_object}'.")

    job_version = config.sync_version_field.strip().lower()
    if job_version not in job_obj.fields:
        issues.append(f"Sync version field '{config.sync_version_field}' is missing on '{config.job_object}'.")
    else:
        f = job_obj.fields[job_version]
        if f.field_type != "Number":
            issues.append(f"Sync version field '{config.sync_version_field}' on '{config.job_object}' must be Number, got '{f.field_type}'.")

    # 3. Candidate Fields Verification
    for cand_field in config.candidate_fields:
        cf_name = cand_field.strip().lower()
        if cf_name not in job_obj.fields:
            issues.append(f"Candidate-owned field '{cand_field}' is missing on '{config.job_object}'.")
            continue
        f = job_obj.fields[cf_name]
        if f.required:
            issues.append(f"Candidate field '{cand_field}' cannot be required on insert (machine payloads omit candidate fields).")

        # Specific candidate field checks
        if "progress" in cf_name:
            if f.field_type != "Picklist":
                issues.append(f"Application progress field '{cand_field}' must be Picklist, got '{f.field_type}'.")
            if f.default_picklist_value != "New":
                issues.append(
                    f"Application progress field '{cand_field}' creation default must be 'New', got '{f.default_picklist_value}'."
                )
            expected_progress = {"New", "Review", "Shortlisted", "Applied", "Interviewing", "Offer", "Rejected", "Withdrawn", "Archived"}
            missing_vals = expected_progress - set(f.picklist_values)
            if missing_vals:
                issues.append(f"Application progress picklist is missing foundation values: {sorted(missing_vals)}")

    # 4. Validation Rules Verification (Format and Immutability)
    comp_rules = comp_obj.validation_rules
    has_comp_fmt = any("format" in r for r in comp_rules)
    has_comp_imm = any("immutable" in r or "immutability" in r for r in comp_rules)
    if not has_comp_fmt:
        warnings.append(f"No UUID format validation rule found on '{config.company_object}'.")
    if not has_comp_imm:
        warnings.append(f"No UUID immutability validation rule found on '{config.company_object}'.")

    job_rules = job_obj.validation_rules
    has_job_fmt = any("format" in r for r in job_rules)
    has_job_imm = any("immutable" in r or "immutability" in r for r in job_rules)
    if not has_job_fmt:
        warnings.append(f"No UUID format validation rule found on '{config.job_object}'.")
    if not has_job_imm:
        warnings.append(f"No UUID immutability validation rule found on '{config.job_object}'.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )




# ==============================================================================
# SF-03: UI Metadata (ListViews, Layouts, CompactLayouts, Flexipages, Reports)
# ==============================================================================


@dataclass(frozen=True)
class ListViewFilter:
    """Filter condition in a ListView."""

    field: str
    operation: str
    value: str | None


@dataclass(frozen=True)
class ListViewMetadata:
    """Parsed ListView metadata."""

    full_name: str
    label: str
    filter_scope: str
    columns: tuple[str, ...]
    filters: tuple[ListViewFilter, ...] = ()
    boolean_filter: str | None = None


@dataclass(frozen=True)
class CompactLayoutMetadata:
    """Parsed CompactLayout metadata."""

    full_name: str
    label: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LayoutItemMetadata:
    """Field item within a page layout column."""

    field: str
    behavior: str  # "Edit", "Readonly", "Required"


@dataclass(frozen=True)
class LayoutSectionMetadata:
    """Section within a page layout."""

    label: str
    custom_label: bool
    detail_heading: bool
    edit_heading: bool
    style: str
    items: tuple[LayoutItemMetadata, ...]


@dataclass(frozen=True)
class RelatedListMetadata:
    """Related list entry in a page layout."""

    related_list: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LayoutMetadata:
    """Parsed Layout metadata."""

    name: str
    sections: tuple[LayoutSectionMetadata, ...]
    related_lists: tuple[RelatedListMetadata, ...] = ()


@dataclass(frozen=True)
class FlexiPageComponentMetadata:
    """Component instance in a Lightning FlexiPage."""

    component_name: str
    identifier: str
    rich_text_value: str | None = None
    visibility_left_value: str | None = None
    visibility_operator: str | None = None
    visibility_right_value: str | None = None


@dataclass(frozen=True)
class FlexiPageRegionMetadata:
    """Region within a Lightning FlexiPage."""

    name: str
    region_type: str
    components: tuple[FlexiPageComponentMetadata, ...]


@dataclass(frozen=True)
class FlexiPageMetadata:
    """Parsed Lightning FlexiPage record page metadata."""

    name: str
    master_label: str
    sobject_type: str
    template: str
    page_type: str
    regions: tuple[FlexiPageRegionMetadata, ...]


@dataclass(frozen=True)
class CustomTabMetadata:
    """Parsed CustomTab metadata."""

    name: str
    custom_object: bool
    motif: str | None
    description: str | None = None


@dataclass(frozen=True)
class CustomApplicationMetadata:
    """Parsed CustomApplication metadata."""

    name: str
    label: str
    form_factors: tuple[str, ...]
    nav_type: str
    tabs: tuple[str, ...]
    ui_type: str
    description: str | None = None


@dataclass(frozen=True)
class ReportTypeMetadata:
    """Parsed ReportType metadata."""

    name: str
    label: str
    base_object: str
    outer_join: bool
    relationship: str | None
    sections: tuple[str, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ReportFilterItem:
    """Filter criterion in a Report."""

    column: str
    operator: str
    value: str | None


@dataclass(frozen=True)
class ReportMetadata:
    """Parsed Report metadata."""

    name: str
    label: str
    report_type: str
    format: str
    columns: tuple[str, ...]
    groupings_down: tuple[str, ...]
    boolean_filter: str | None = None
    filters: tuple[ReportFilterItem, ...] = ()
    description: str | None = None


def load_salesforce_dx_list_views(object_dir: Path) -> dict[str, ListViewMetadata]:
    """Load all ListViews defined under an object's listViews directory."""
    views_dir = object_dir / "listViews"
    views: dict[str, ListViewMetadata] = {}
    if not views_dir.is_dir():
        return views

    for p in views_dir.glob("*.listView-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        full_name = _find_text(root, "fullName") or p.stem.replace(".listView-meta", "")
        label = _find_text(root, "label") or full_name
        filter_scope = _find_text(root, "filterScope") or "Everything"
        boolean_filter = _find_text(root, "booleanFilter")

        columns: list[str] = []
        filters: list[ListViewFilter] = []

        for child in root:
            t = _tag_name(child)
            if t == "columns":
                if child.text and child.text.strip():
                    columns.append(child.text.strip())
            elif t == "filters":
                field_val = _find_text(child, "field") or ""
                op_val = _find_text(child, "operation") or "equals"
                v_val = _find_text(child, "value")
                filters.append(ListViewFilter(field=field_val, operation=op_val, value=v_val))

        views[full_name] = ListViewMetadata(
            full_name=full_name,
            label=label,
            filter_scope=filter_scope,
            columns=tuple(columns),
            filters=tuple(filters),
            boolean_filter=boolean_filter,
        )

    return views


def load_salesforce_dx_compact_layouts(object_dir: Path) -> dict[str, CompactLayoutMetadata]:
    """Load CompactLayouts defined under an object's compactLayouts directory."""
    cl_dir = object_dir / "compactLayouts"
    cls: dict[str, CompactLayoutMetadata] = {}
    if not cl_dir.is_dir():
        return cls

    for p in cl_dir.glob("*.compactLayout-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        full_name = _find_text(root, "fullName") or p.stem.replace(".compactLayout-meta", "")
        label = _find_text(root, "label") or full_name

        fields: list[str] = []
        for child in root:
            if _tag_name(child) == "fields":
                if child.text and child.text.strip():
                    fields.append(child.text.strip())

        cls[full_name] = CompactLayoutMetadata(
            full_name=full_name,
            label=label,
            fields=tuple(fields),
        )

    return cls


def load_salesforce_dx_layouts(layouts_dir: Path) -> dict[str, LayoutMetadata]:
    """Load page layouts from layouts directory."""
    layouts: dict[str, LayoutMetadata] = {}
    if not layouts_dir.is_dir():
        return layouts

    for p in layouts_dir.glob("*.layout-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".layout-meta", "")

        sections: list[LayoutSectionMetadata] = []
        related_lists: list[RelatedListMetadata] = []

        for child in root:
            t = _tag_name(child)
            if t == "layoutSections":
                sec_label = _find_text(child, "label") or ""
                custom_lbl = _find_bool(child, "customLabel", default=False)
                det_head = _find_bool(child, "detailHeading", default=False)
                edit_head = _find_bool(child, "editHeading", default=False)
                sec_style = _find_text(child, "style") or ""

                items: list[LayoutItemMetadata] = []
                for col in child:
                    if _tag_name(col) == "layoutColumns":
                        for item in col:
                            if _tag_name(item) == "layoutItems":
                                fld = _find_text(item, "field")
                                beh = _find_text(item, "behavior") or "Edit"
                                if fld:
                                    items.append(LayoutItemMetadata(field=fld, behavior=beh))

                sections.append(
                    LayoutSectionMetadata(
                        label=sec_label,
                        custom_label=custom_lbl,
                        detail_heading=det_head,
                        edit_heading=edit_head,
                        style=sec_style,
                        items=tuple(items),
                    )
                )
            elif t == "relatedLists":
                rel_name = _find_text(child, "relatedList") or ""
                rel_fields: list[str] = []
                for sub in child:
                    if _tag_name(sub) == "fields":
                        if sub.text and sub.text.strip():
                            rel_fields.append(sub.text.strip())
                related_lists.append(RelatedListMetadata(related_list=rel_name, fields=tuple(rel_fields)))

        layouts[name] = LayoutMetadata(
            name=name,
            sections=tuple(sections),
            related_lists=tuple(related_lists),
        )

    return layouts


def load_salesforce_dx_flexipages(flexipages_dir: Path) -> dict[str, FlexiPageMetadata]:
    """Load Lightning FlexiPages."""
    pages: dict[str, FlexiPageMetadata] = {}
    if not flexipages_dir.is_dir():
        return pages

    for p in flexipages_dir.glob("*.flexipage-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".flexipage-meta", "")
        master_label = _find_text(root, "masterLabel") or name
        sobject_type = _find_text(root, "sobjectType") or ""
        page_type = _find_text(root, "type") or "RecordPage"

        template_elem = None
        for c in root:
            if _tag_name(c) == "template":
                template_elem = c
                break
        template_name = _find_text(template_elem, "name") if template_elem is not None else ""

        regions: list[FlexiPageRegionMetadata] = []
        for reg in root:
            if _tag_name(reg) == "flexiPageRegions":
                reg_name = _find_text(reg, "name") or ""
                reg_type = _find_text(reg, "type") or ""

                components: list[FlexiPageComponentMetadata] = []
                for item in reg:
                    if _tag_name(item) == "itemInstances":
                        for comp in item:
                            if _tag_name(comp) == "componentInstance":
                                c_name = _find_text(comp, "componentName") or ""
                                c_id = _find_text(comp, "identifier") or ""
                                rich_text = None
                                vis_left = None
                                vis_op = None
                                vis_right = None

                                for prop in comp:
                                    if _tag_name(prop) == "componentInstanceProperties":
                                        p_name = _find_text(prop, "name")
                                        if p_name == "richTextValue":
                                            rich_text = _find_text(prop, "value")
                                    elif _tag_name(prop) == "visibilityRule":
                                        for crit in prop:
                                            if _tag_name(crit) == "criteria":
                                                vis_left = _find_text(crit, "leftValue")
                                                vis_op = _find_text(crit, "operator")
                                                vis_right = _find_text(crit, "rightValue")

                                components.append(
                                    FlexiPageComponentMetadata(
                                        component_name=c_name,
                                        identifier=c_id,
                                        rich_text_value=rich_text,
                                        visibility_left_value=vis_left,
                                        visibility_operator=vis_op,
                                        visibility_right_value=vis_right,
                                    )
                                )

                regions.append(
                    FlexiPageRegionMetadata(
                        name=reg_name,
                        region_type=reg_type,
                        components=tuple(components),
                    )
                )

        pages[name] = FlexiPageMetadata(
            name=name,
            master_label=master_label,
            sobject_type=sobject_type,
            template=template_name or "",
            page_type=page_type,
            regions=tuple(regions),
        )

    return pages


def load_salesforce_dx_tabs(tabs_dir: Path) -> dict[str, CustomTabMetadata]:
    """Load CustomTabs from tabs directory."""
    tabs: dict[str, CustomTabMetadata] = {}
    if not tabs_dir.is_dir():
        return tabs

    for p in tabs_dir.glob("*.tab-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".tab-meta", "")
        is_custom_obj = _find_bool(root, "customObject", default=False)
        motif = _find_text(root, "motif")
        desc = _find_text(root, "description")

        tabs[name] = CustomTabMetadata(
            name=name,
            custom_object=is_custom_obj,
            motif=motif,
            description=desc,
        )

    return tabs


def load_salesforce_dx_applications(apps_dir: Path) -> dict[str, CustomApplicationMetadata]:
    """Load CustomApplications from applications directory."""
    apps: dict[str, CustomApplicationMetadata] = {}
    if not apps_dir.is_dir():
        return apps

    for p in apps_dir.glob("*.app-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".app-meta", "")
        label = _find_text(root, "label") or name
        nav_type = _find_text(root, "navType") or "Standard"
        ui_type = _find_text(root, "uiType") or "Lightning"
        desc = _find_text(root, "description")

        form_factors: list[str] = []
        tabs: list[str] = []

        for child in root:
            t = _tag_name(child)
            if t == "formFactors":
                if child.text and child.text.strip():
                    form_factors.append(child.text.strip())
            elif t == "tabs":
                if child.text and child.text.strip():
                    tabs.append(child.text.strip())

        apps[name] = CustomApplicationMetadata(
            name=name,
            label=label,
            form_factors=tuple(form_factors),
            nav_type=nav_type,
            tabs=tuple(tabs),
            ui_type=ui_type,
            description=desc,
        )

    return apps


def load_salesforce_dx_report_types(report_types_dir: Path) -> dict[str, ReportTypeMetadata]:
    """Load ReportTypes from reportTypes directory."""
    types: dict[str, ReportTypeMetadata] = {}
    if not report_types_dir.is_dir():
        return types

    for p in report_types_dir.glob("*.reportType-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".reportType-meta", "")
        label = _find_text(root, "label") or name
        base_obj = _find_text(root, "baseObject") or ""

        outer_join = False
        relationship = None
        for c in root:
            if _tag_name(c) == "join":
                outer_join = _find_bool(c, "outerJoin", default=False)
                relationship = _find_text(c, "relationship")

        sections: list[str] = []
        columns: list[str] = []
        for sec in root:
            if _tag_name(sec) == "sections":
                sec_lbl = _find_text(sec, "masterLabel") or ""
                sections.append(sec_lbl)
                for col in sec:
                    if _tag_name(col) == "columns":
                        fld = _find_text(col, "field")
                        if fld:
                            columns.append(fld)

        types[name] = ReportTypeMetadata(
            name=name,
            label=label,
            base_object=base_obj,
            outer_join=outer_join,
            relationship=relationship,
            sections=tuple(sections),
            columns=tuple(columns),
        )

    return types


def load_salesforce_dx_reports(reports_dir: Path) -> dict[str, ReportMetadata]:
    """Load Reports from reports directory (including subdirectories/folders)."""
    reports: dict[str, ReportMetadata] = {}
    if not reports_dir.is_dir():
        return reports

    for p in reports_dir.rglob("*.report-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        rel_folder = p.parent.name
        report_name = f"{rel_folder}/{p.stem.replace('.report-meta', '')}" if rel_folder != reports_dir.name else p.stem.replace('.report-meta', '')
        label = _find_text(root, "name") or report_name
        report_type = _find_text(root, "reportType") or ""
        report_format = _find_text(root, "format") or "Summary"
        boolean_filter = _find_text(root, "booleanFilter")
        desc = _find_text(root, "description")

        columns: list[str] = []
        groupings_down: list[str] = []
        filters: list[ReportFilterItem] = []

        for child in root:
            t = _tag_name(child)
            if t == "columns":
                fld = _find_text(child, "field")
                if fld:
                    columns.append(fld)
            elif t == "groupingsDown":
                fld = _find_text(child, "field")
                if fld:
                    groupings_down.append(fld)
            elif t == "filter":
                for crit in child:
                    if _tag_name(crit) == "criteriaItems":
                        col = _find_text(crit, "column") or ""
                        op = _find_text(crit, "operator") or "equals"
                        val = _find_text(crit, "value")
                        filters.append(ReportFilterItem(column=col, operator=op, value=val))

        reports[report_name] = ReportMetadata(
            name=report_name,
            label=label,
            report_type=report_type,
            format=report_format,
            columns=tuple(columns),
            groupings_down=tuple(groupings_down),
            boolean_filter=boolean_filter,
            filters=tuple(filters),
            description=desc,
        )

    return reports


def evaluate_list_view_filter(view: ListViewMetadata, record: dict[str, Any], today_date: str) -> bool:
    """Evaluate whether a record matches a list view filter predicate."""
    if not view.filters:
        return True

    results: list[bool] = []
    for f in view.filters:
        val = record.get(f.field)
        val_str = "" if val is None else str(val)

        target_val = f.value if f.value is not None else ""
        if target_val == "TODAY":
            target_val = today_date

        if f.operation == "equals":
            options = [opt.strip() for opt in target_val.split(",")] if target_val else [""]
            results.append(val_str in options)
        elif f.operation == "notEqual":
            results.append(val_str != target_val)
        elif f.operation == "lessOrEqual":
            results.append(bool(val_str and val_str <= target_val))
        elif f.operation == "greaterThan":
            results.append(bool(val_str and val_str > target_val))
        else:
            raise ValueError(f"Unsupported operation: {f.operation}")

    if view.boolean_filter:
        expr = view.boolean_filter.strip()
        for idx in range(len(results), 0, -1):
            expr = expr.replace(str(idx), str(results[idx - 1]))
        expr = expr.replace("AND", "and").replace("OR", "or").replace("NOT", "not")
        return bool(eval(expr, {"__builtins__": None}, {}))
    else:
        return all(results)


def evaluate_report_filter(report: ReportMetadata, record: dict[str, Any]) -> bool:
    """Evaluate whether a record matches a report filter predicate."""
    if not report.filters:
        return True

    results: list[bool] = []
    for f in report.filters:
        field_name = f.column.split(".")[-1]
        val = record.get(field_name)
        val_str = "" if val is None else str(val)
        target_val = f.value if f.value is not None else ""

        if f.operator == "equals":
            options = [opt.strip() for opt in target_val.split(",")] if target_val else [""]
            results.append(val_str in options)
        elif f.operator == "notEqual":
            results.append(val_str != target_val)
        else:
            raise ValueError(f"Unsupported operator: {f.operator}")

    if report.boolean_filter:
        expr = report.boolean_filter.strip()
        for idx in range(len(results), 0, -1):
            expr = expr.replace(str(idx), str(results[idx - 1]))
        expr = expr.replace("AND", "and").replace("OR", "or").replace("NOT", "not")
        return bool(eval(expr, {"__builtins__": None}, {}))
    else:
        return all(results)


def validate_sf03_ui_metadata(sf_main_dir: Path) -> MetadataCompatibilityReport:
    """Validate that all SF-03 UI components exist and satisfy R08 requirements."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Custom Object Job__c compact layout assignment
    job_obj_path = sf_main_dir / "objects" / "Job__c" / "Job__c.object-meta.xml"
    if not job_obj_path.is_file():
        issues.append(f"Job__c object XML not found at {job_obj_path}")
    else:
        tree = ET.parse(job_obj_path)
        cla = _find_text(tree.getroot(), "compactLayoutAssignment")
        if cla != "JA_Tracking":
            issues.append(f"Job__c compactLayoutAssignment must be 'JA_Tracking', got '{cla}'")

    # 2. Compact Layout JA_Tracking
    job_cls = load_salesforce_dx_compact_layouts(sf_main_dir / "objects" / "Job__c")
    if "JA_Tracking" not in job_cls:
        issues.append("CompactLayout 'JA_Tracking' is missing under Job__c/compactLayouts/")
    else:
        cl = job_cls["JA_Tracking"]
        req_cl_fields = {
            "Name",
            "Company__c",
            "Application_Progress__c",
            "Assessment_Disposition__c",
            "Availability__c",
            "Follow_Up_Date__c",
        }
        present_cl_fields = set(cl.fields)
        missing_cl = req_cl_fields - present_cl_fields
        if missing_cl:
            issues.append(f"CompactLayout 'JA_Tracking' missing required fields: {sorted(missing_cl)}")

    # 3. List Views (7 required queues)
    job_views = load_salesforce_dx_list_views(sf_main_dir / "objects" / "Job__c")
    expected_views = {
        "JA_Eligible_Jobs",
        "JA_Review_Jobs",
        "JA_Shortlist",
        "JA_Applications",
        "JA_Follow_Ups_Due",
        "JA_Follow_Ups_Upcoming",
        "JA_Tracked_History",
    }
    missing_views = expected_views - set(job_views.keys())
    if missing_views:
        issues.append(f"Missing required Job__c ListViews: {sorted(missing_views)}")

    for v_name, v_meta in job_views.items():
        if v_name in expected_views:
            if v_meta.filter_scope != "Everything":
                issues.append(f"ListView {v_name} filterScope must be 'Everything' (not 'Mine'), got '{v_meta.filter_scope}'")
            # Verify required columns exist
            for col in ("NAME", "Company__c", "Application_Progress__c", "Assessment_Disposition__c", "Availability__c"):
                if col not in v_meta.columns:
                    issues.append(f"ListView {v_name} missing baseline column '{col}'")

    # 4. Layouts
    layouts = load_salesforce_dx_layouts(sf_main_dir / "layouts")
    if "Job__c-JA Candidate Tracking" not in layouts:
        issues.append("Layout 'Job__c-JA Candidate Tracking' is missing")
    else:
        jl = layouts["Job__c-JA Candidate Tracking"]
        sec_names = [s.label for s in jl.sections]
        for req_sec in ("Your Application", "Machine Assessment", "Posting Availability and Source", "Technical Reference"):
            if req_sec not in sec_names:
                issues.append(f"Job__c layout missing required section: '{req_sec}'")

        # Verify candidate fields are Edit
        cand_fields = {
            "Application_Progress__c",
            "Candidate_Decision__c",
            "Candidate_Notes__c",
            "Follow_Up_Date__c",
            "Interview_Date__c",
        }
        mach_fields = {
            "Assessment_Disposition__c",
            "Relevance_Score__c",
            "Score_Scale__c",
            "Last_Evaluated_At__c",
            "Assessment_Reasons__c",
            "Availability__c",
            "Source_URLs__c",
            "Canonical_Job_Id__c",
            "Machine_Sync_Version__c",
            "Sync_Operation_Marker__c",
        }
        for sec in jl.sections:
            for it in sec.items:
                if it.field in cand_fields:
                    if it.behavior != "Edit":
                        issues.append(f"Candidate field '{it.field}' in layout must have behavior 'Edit', got '{it.behavior}'")
                elif it.field in mach_fields:
                    if it.behavior != "Readonly":
                        issues.append(f"Machine field '{it.field}' in layout must have behavior 'Readonly', got '{it.behavior}'")

    if "Company__c-JA Company Overview" not in layouts:
        issues.append("Layout 'Company__c-JA Company Overview' is missing")
    else:
        cl = layouts["Company__c-JA Company Overview"]
        rel_lists = [r.related_list for r in cl.related_lists]
        if "Job__c.Company__c" not in rel_lists:
            issues.append("Company__c layout missing related list 'Job__c.Company__c'")

    # 5. FlexiPage
    flexipages = load_salesforce_dx_flexipages(sf_main_dir / "flexipages")
    if "JA_Job_Tracking" not in flexipages:
        issues.append("FlexiPage 'JA_Job_Tracking' is missing")
    else:
        fp = flexipages["JA_Job_Tracking"]
        if fp.sobject_type != "Job__c":
            issues.append(f"FlexiPage sobjectType must be 'Job__c', got '{fp.sobject_type}'")
        all_comps = [c for r in fp.regions for c in r.components]
        comp_names = [c.component_name for c in all_comps]
        if "force:highlightsPanel" not in comp_names:
            issues.append("FlexiPage missing force:highlightsPanel")
        if "force:detailPanel" not in comp_names:
            issues.append("FlexiPage missing force:detailPanel")

        # Verify review banner and text guidance
        banner_found = False
        decision_text_found = False
        missing_assessment_banner_found = False
        for c in all_comps:
            if c.rich_text_value:
                if "Review required: eligibility or assessment is unresolved" in c.rich_text_value:
                    banner_found = True
                    if c.visibility_left_value != "{!Record.Assessment_Disposition__c}" or c.visibility_right_value != "Review":
                        issues.append("Review banner has incorrect visibility rule")
                if "Assessment missing" in c.rich_text_value:
                    missing_assessment_banner_found = True
                    if c.visibility_left_value != "{!Record.Assessment_Disposition__c}" or (c.visibility_right_value or "") != "":
                        issues.append("Missing assessment banner has incorrect visibility rule")
                if "Your decision changes your tracking workflow only" in c.rich_text_value:
                    decision_text_found = True

        if not banner_found:
            issues.append("FlexiPage missing review required guidance banner")
        if not missing_assessment_banner_found:
            issues.append("FlexiPage missing assessment missing guidance banner")
        if not decision_text_found:
            issues.append("FlexiPage missing decision guidance text")

    # 6. Tabs
    tabs = load_salesforce_dx_tabs(sf_main_dir / "tabs")
    if "Job__c" not in tabs:
        issues.append("CustomTab 'Job__c' is missing")
    if "Company__c" not in tabs:
        issues.append("CustomTab 'Company__c' is missing")

    # 7. Application
    apps = load_salesforce_dx_applications(sf_main_dir / "applications")
    if "Job_Tracker" not in apps:
        issues.append("CustomApplication 'Job_Tracker' is missing")
    else:
        app = apps["Job_Tracker"]
        if "Job__c" not in app.tabs or "Company__c" not in app.tabs:
            issues.append("CustomApplication 'Job_Tracker' missing Job__c or Company__c tabs")

    # 8. ReportType
    report_types = load_salesforce_dx_report_types(sf_main_dir / "reportTypes")
    if "JA_Jobs" not in report_types:
        issues.append("ReportType 'JA_Jobs' is missing")
    else:
        rt = report_types["JA_Jobs"]
        if rt.base_object != "Job__c":
            issues.append(f"ReportType baseObject must be 'Job__c', got '{rt.base_object}'")
        if not rt.outer_join:
            issues.append("ReportType must configure outerJoin=true on Company__r so jobs without Company are not dropped")

    # 9. Reports
    reports = load_salesforce_dx_reports(sf_main_dir / "reports")
    expected_reports = {
        "Job_Tracker/JA_Eligible_Review",
        "Job_Tracker/JA_Shortlist",
        "Job_Tracker/JA_Applications",
        "Job_Tracker/JA_Follow_Ups",
    }
    missing_reps = expected_reports - set(reports.keys())
    if missing_reps:
        issues.append(f"Missing required Reports under Job_Tracker: {sorted(missing_reps)}")

    for r_name in expected_reports.intersection(set(reports.keys())):
        rep = reports[r_name]
        if rep.report_type != "JA_Jobs":
            issues.append(f"Report {r_name} must use ReportType 'JA_Jobs', got '{rep.report_type}'")
        if rep.format != "Summary":
            issues.append(f"Report {r_name} must have format 'Summary', got '{rep.format}'")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )



# --- Permission Set & External Client App Metadata (SF-02) ---


@dataclass(frozen=True)
class ObjectPermission:
    """Parsed ObjectPermission attributes."""

    object_name: str
    allow_create: bool = False
    allow_delete: bool = False
    allow_edit: bool = False
    allow_read: bool = False
    modify_all_records: bool = False
    view_all_records: bool = False


@dataclass(frozen=True)
class FieldPermission:
    """Parsed FieldPermission attributes."""

    field: str
    editable: bool = False
    readable: bool = False


@dataclass(frozen=True)
class PermissionSetMetadata:
    """Parsed PermissionSet metadata attributes."""

    name: str
    label: str
    description: str | None = None
    has_activation_required: bool = False
    object_permissions: dict[str, ObjectPermission] = field(default_factory=dict)
    field_permissions: dict[str, FieldPermission] = field(default_factory=dict)
    user_permissions: set[str] = field(default_factory=set)
    class_accesses: dict[str, bool] = field(default_factory=dict)
    flow_accesses: dict[str, bool] = field(default_factory=dict)
    custom_permissions: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalClientAppMetadata:
    """Parsed ExternalClientApplication header metadata."""

    name: str
    label: str
    contact_email: str
    distribution_state: str
    is_protected: bool = False
    description: str | None = None


@dataclass(frozen=True)
class EcaOauthSettingsMetadata:
    """Parsed ExtlClntAppOauthSettings metadata."""

    name: str
    external_client_application: str
    label: str
    callback_url: str
    is_pkce_required: bool = True
    is_consumer_secret_optional: bool = False
    is_secret_required_for_refresh: bool = False
    is_introspect_all_tokens: bool = False
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EcaOauthPoliciesMetadata:
    """Parsed ExtlClntAppOauthConfigurablePolicies metadata."""

    name: str
    external_client_application: str
    label: str
    ip_relaxation_policy_type: str = "Enforce"
    permitted_users_policy_type: str = "AdminApprovedPreAuthorized"
    refresh_token_policy_type: str = "SpecificLifetime"
    refresh_token_validity_period: int | None = None
    refresh_token_validity_unit: str | None = None
    session_timeout_in_minutes: int | None = None


def load_permission_set(path: Path) -> PermissionSetMetadata:
    """Parse a Salesforce DX PermissionSet XML file."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Permission set file not found: {resolved}")

    tree = ET.parse(resolved)
    root = tree.getroot()

    label = _find_text(root, "label") or resolved.stem.replace(".permissionset-meta", "")
    description = _find_text(root, "description")
    activation_required = _find_bool(root, "hasActivationRequired", default=False)

    object_perms: dict[str, ObjectPermission] = {}
    field_perms: dict[str, FieldPermission] = {}
    user_perms: set[str] = set()

    class_accesses: dict[str, bool] = {}
    flow_accesses: dict[str, bool] = {}
    custom_perms: dict[str, bool] = {}

    for child in root:
        t = _tag_name(child)
        if t == "classAccesses":
            c_name = _find_text(child, "apexClass")
            enabled = _find_bool(child, "enabled")
            if c_name:
                class_accesses[c_name.lower()] = enabled
        elif t == "flowAccesses":
            fl_name = _find_text(child, "flow")
            enabled = _find_bool(child, "enabled")
            if fl_name:
                flow_accesses[fl_name.lower()] = enabled
        elif t == "customPermissions":
            cp_name = _find_text(child, "name")
            enabled = _find_bool(child, "enabled")
            if cp_name:
                custom_perms[cp_name.lower()] = enabled
        elif t == "objectPermissions":
            obj_name = _find_text(child, "object")
            if obj_name:
                object_perms[obj_name.lower()] = ObjectPermission(
                    object_name=obj_name,
                    allow_create=_find_bool(child, "allowCreate"),
                    allow_delete=_find_bool(child, "allowDelete"),
                    allow_edit=_find_bool(child, "allowEdit"),
                    allow_read=_find_bool(child, "allowRead"),
                    modify_all_records=_find_bool(child, "modifyAllRecords"),
                    view_all_records=_find_bool(child, "viewAllRecords"),
                )
        elif t == "fieldPermissions":
            f_name = _find_text(child, "field")
            if f_name:
                field_perms[f_name.lower()] = FieldPermission(
                    field=f_name,
                    editable=_find_bool(child, "editable"),
                    readable=_find_bool(child, "readable"),
                )
        elif t == "userPermissions":
            u_name = _find_text(child, "name")
            enabled = _find_bool(child, "enabled")
            if u_name and enabled:
                user_perms.add(u_name)

    return PermissionSetMetadata(
        name=resolved.stem.replace(".permissionset-meta", ""),
        label=label,
        description=description,
        has_activation_required=activation_required,
        object_permissions=object_perms,
        field_permissions=field_perms,
        user_permissions=user_perms,
        class_accesses=class_accesses,
        flow_accesses=flow_accesses,
        custom_permissions=custom_perms,
    )


def validate_worker_permission_set(
    perm_set: PermissionSetMetadata,
    config: SyncMappingConfig,
) -> MetadataCompatibilityReport:
    """Validate that PermissionSet strictly satisfies SF-02 least-privilege requirements."""
    issues: list[str] = []
    warnings: list[str] = []

    comp_name = config.company_object.lower()
    job_name = config.job_object.lower()

    # 1. Object permissions
    for target, obj_label in [(comp_name, config.company_object), (job_name, config.job_object)]:
        if target not in perm_set.object_permissions:
            issues.append(f"Permission set is missing objectPermissions for '{obj_label}'.")
            continue
        op = perm_set.object_permissions[target]
        if not op.allow_read:
            issues.append(f"Permission set must grant allowRead on '{obj_label}'.")
        if not op.allow_create:
            issues.append(f"Permission set must grant allowCreate on '{obj_label}'.")
        if not op.allow_edit:
            issues.append(f"Permission set must grant allowEdit on '{obj_label}'.")
        if op.allow_delete:
            issues.append(f"Permission set must NOT grant allowDelete on '{obj_label}' (least privilege).")
        if op.view_all_records:
            issues.append(f"Permission set must NOT grant viewAllRecords on '{obj_label}'.")
        if op.modify_all_records:
            issues.append(f"Permission set must NOT grant modifyAllRecords on '{obj_label}'.")

    # Forbidden objects
    for obj_key, op in perm_set.object_permissions.items():
        if obj_key not in (comp_name, job_name, "generation_request__c", "ja_artifact_review__c", "ja_artifact_review_event__c"):
            issues.append(f"Permission set grants unauthorized object access to '{op.object_name}'.")

    # 2. Field permissions - Machine fields must be R/W (except standard Name which doesn't have FLS)
    machine_fields: list[tuple[str, str]] = [
        (config.company_object, config.company_external_id_field),
        (config.company_object, config.sync_marker_field),
        (config.company_object, config.sync_version_field),
        (config.job_object, config.job_external_id_field),
        (config.job_object, config.job_company_lookup_field),
        (config.job_object, config.availability_field),
        (config.job_object, config.disposition_field),
        (config.job_object, config.reason_field),
        (config.job_object, config.score_field),
        (config.job_object, config.score_scale_field),
        (config.job_object, config.last_evaluated_field),
        (config.job_object, config.source_urls_field),
        (config.job_object, config.sync_marker_field),
        (config.job_object, config.sync_version_field),
    ]
    if config.company_name_field.lower() != "name":
        machine_fields.append((config.company_object, config.company_name_field))
    if config.title_field.lower() != "name":
        machine_fields.append((config.job_object, config.title_field))

    for obj_name, f_name in machine_fields:
        full_field = f"{obj_name}.{f_name}".lower()
        if full_field not in perm_set.field_permissions:
            issues.append(f"Missing fieldPermission for machine field '{obj_name}.{f_name}'.")
        else:
            fp = perm_set.field_permissions[full_field]
            if not fp.readable:
                issues.append(f"Machine field '{obj_name}.{f_name}' must be readable.")
            if not fp.editable:
                issues.append(f"Machine field '{obj_name}.{f_name}' must be editable.")

    # 3. Field permissions - Candidate fields must be strictly READ-ONLY
    for cand_field in config.candidate_fields:
        full_field = f"{config.job_object}.{cand_field}".lower()
        if full_field not in perm_set.field_permissions:
            issues.append(f"Missing fieldPermission for candidate field '{config.job_object}.{cand_field}'.")
        else:
            fp = perm_set.field_permissions[full_field]
            if not fp.readable:
                issues.append(f"Candidate field '{config.job_object}.{cand_field}' must be readable for backup.")
            if fp.editable:
                issues.append(
                    f"Candidate field '{config.job_object}.{cand_field}' must NOT be editable (least privilege; candidate preservation)."
                )

    # 4. User permissions
    if "ViewSetup" not in perm_set.user_permissions:
        issues.append("Permission set must grant 'ViewSetup' userPermission for REST /limits endpoint.")

    forbidden_user_perms = {"ModifyAllData", "ViewAllData", "CustomizeApplication", "ManageUsers"}
    present_forbidden = forbidden_user_perms.intersection(perm_set.user_permissions)
    if present_forbidden:
        issues.append(f"Permission set grants forbidden administrative userPermissions: {sorted(present_forbidden)}.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


# ==============================================================================
# SF-03: UI Metadata (ListViews, Layouts, CompactLayouts, Flexipages, Reports)
# ==============================================================================


@dataclass(frozen=True)
class ListViewFilter:
    """Filter condition in a ListView."""

    field: str
    operation: str
    value: str | None


@dataclass(frozen=True)
class ListViewMetadata:
    """Parsed ListView metadata."""

    full_name: str
    label: str
    filter_scope: str
    columns: tuple[str, ...]
    filters: tuple[ListViewFilter, ...] = ()
    boolean_filter: str | None = None


@dataclass(frozen=True)
class CompactLayoutMetadata:
    """Parsed CompactLayout metadata."""

    full_name: str
    label: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LayoutItemMetadata:
    """Field item within a page layout column."""

    field: str
    behavior: str  # "Edit", "Readonly", "Required"


@dataclass(frozen=True)
class LayoutSectionMetadata:
    """Section within a page layout."""

    label: str
    custom_label: bool
    detail_heading: bool
    edit_heading: bool
    style: str
    items: tuple[LayoutItemMetadata, ...]


@dataclass(frozen=True)
class RelatedListMetadata:
    """Related list entry in a page layout."""

    related_list: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LayoutMetadata:
    """Parsed Layout metadata."""

    name: str
    sections: tuple[LayoutSectionMetadata, ...]
    related_lists: tuple[RelatedListMetadata, ...] = ()


@dataclass(frozen=True)
class FlexiPageComponentMetadata:
    """Component instance in a Lightning FlexiPage."""

    component_name: str
    identifier: str
    rich_text_value: str | None = None
    visibility_left_value: str | None = None
    visibility_operator: str | None = None
    visibility_right_value: str | None = None


@dataclass(frozen=True)
class FlexiPageRegionMetadata:
    """Region within a Lightning FlexiPage."""

    name: str
    region_type: str
    components: tuple[FlexiPageComponentMetadata, ...]


@dataclass(frozen=True)
class FlexiPageMetadata:
    """Parsed Lightning FlexiPage record page metadata."""

    name: str
    master_label: str
    sobject_type: str
    template: str
    page_type: str
    regions: tuple[FlexiPageRegionMetadata, ...]


@dataclass(frozen=True)
class CustomTabMetadata:
    """Parsed CustomTab metadata."""

    name: str
    custom_object: bool
    motif: str | None
    description: str | None = None


@dataclass(frozen=True)
class CustomApplicationMetadata:
    """Parsed CustomApplication metadata."""

    name: str
    label: str
    form_factors: tuple[str, ...]
    nav_type: str
    tabs: tuple[str, ...]
    ui_type: str
    description: str | None = None


@dataclass(frozen=True)
class ReportTypeMetadata:
    """Parsed ReportType metadata."""

    name: str
    label: str
    base_object: str
    outer_join: bool
    relationship: str | None
    sections: tuple[str, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ReportFilterItem:
    """Filter criterion in a Report."""

    column: str
    operator: str
    value: str | None


@dataclass(frozen=True)
class ReportMetadata:
    """Parsed Report metadata."""

    name: str
    label: str
    report_type: str
    format: str
    columns: tuple[str, ...]
    groupings_down: tuple[str, ...]
    boolean_filter: str | None = None
    filters: tuple[ReportFilterItem, ...] = ()
    description: str | None = None


def load_salesforce_dx_list_views(object_dir: Path) -> dict[str, ListViewMetadata]:
    """Load all ListViews defined under an object's listViews directory."""
    views_dir = object_dir / "listViews"
    views: dict[str, ListViewMetadata] = {}
    if not views_dir.is_dir():
        return views

    for p in views_dir.glob("*.listView-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        full_name = _find_text(root, "fullName") or p.stem.replace(".listView-meta", "")
        label = _find_text(root, "label") or full_name
        filter_scope = _find_text(root, "filterScope") or "Everything"
        boolean_filter = _find_text(root, "booleanFilter")

        columns: list[str] = []
        filters: list[ListViewFilter] = []

        for child in root:
            t = _tag_name(child)
            if t == "columns":
                if child.text and child.text.strip():
                    columns.append(child.text.strip())
            elif t == "filters":
                field_val = _find_text(child, "field") or ""
                op_val = _find_text(child, "operation") or "equals"
                v_val = _find_text(child, "value")
                filters.append(ListViewFilter(field=field_val, operation=op_val, value=v_val))

        views[full_name] = ListViewMetadata(
            full_name=full_name,
            label=label,
            filter_scope=filter_scope,
            columns=tuple(columns),
            filters=tuple(filters),
            boolean_filter=boolean_filter,
        )

    return views


def load_salesforce_dx_compact_layouts(object_dir: Path) -> dict[str, CompactLayoutMetadata]:
    """Load CompactLayouts defined under an object's compactLayouts directory."""
    cl_dir = object_dir / "compactLayouts"
    cls: dict[str, CompactLayoutMetadata] = {}
    if not cl_dir.is_dir():
        return cls

    for p in cl_dir.glob("*.compactLayout-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        full_name = _find_text(root, "fullName") or p.stem.replace(".compactLayout-meta", "")
        label = _find_text(root, "label") or full_name

        fields: list[str] = []
        for child in root:
            if _tag_name(child) == "fields":
                if child.text and child.text.strip():
                    fields.append(child.text.strip())

        cls[full_name] = CompactLayoutMetadata(
            full_name=full_name,
            label=label,
            fields=tuple(fields),
        )

    return cls


def load_salesforce_dx_layouts(layouts_dir: Path) -> dict[str, LayoutMetadata]:
    """Load page layouts from layouts directory."""
    layouts: dict[str, LayoutMetadata] = {}
    if not layouts_dir.is_dir():
        return layouts

    for p in layouts_dir.glob("*.layout-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".layout-meta", "")

        sections: list[LayoutSectionMetadata] = []
        related_lists: list[RelatedListMetadata] = []

        for child in root:
            t = _tag_name(child)
            if t == "layoutSections":
                sec_label = _find_text(child, "label") or ""
                custom_lbl = _find_bool(child, "customLabel", default=False)
                det_head = _find_bool(child, "detailHeading", default=False)
                edit_head = _find_bool(child, "editHeading", default=False)
                sec_style = _find_text(child, "style") or ""

                items: list[LayoutItemMetadata] = []
                for col in child:
                    if _tag_name(col) == "layoutColumns":
                        for item in col:
                            if _tag_name(item) == "layoutItems":
                                fld = _find_text(item, "field")
                                beh = _find_text(item, "behavior") or "Edit"
                                if fld:
                                    items.append(LayoutItemMetadata(field=fld, behavior=beh))

                sections.append(
                    LayoutSectionMetadata(
                        label=sec_label,
                        custom_label=custom_lbl,
                        detail_heading=det_head,
                        edit_heading=edit_head,
                        style=sec_style,
                        items=tuple(items),
                    )
                )
            elif t == "relatedLists":
                rel_name = _find_text(child, "relatedList") or ""
                rel_fields: list[str] = []
                for sub in child:
                    if _tag_name(sub) == "fields":
                        if sub.text and sub.text.strip():
                            rel_fields.append(sub.text.strip())
                related_lists.append(RelatedListMetadata(related_list=rel_name, fields=tuple(rel_fields)))

        layouts[name] = LayoutMetadata(
            name=name,
            sections=tuple(sections),
            related_lists=tuple(related_lists),
        )

    return layouts


def load_salesforce_dx_flexipages(flexipages_dir: Path) -> dict[str, FlexiPageMetadata]:
    """Load Lightning FlexiPages."""
    pages: dict[str, FlexiPageMetadata] = {}
    if not flexipages_dir.is_dir():
        return pages

    for p in flexipages_dir.glob("*.flexipage-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".flexipage-meta", "")
        master_label = _find_text(root, "masterLabel") or name
        sobject_type = _find_text(root, "sobjectType") or ""
        page_type = _find_text(root, "type") or "RecordPage"

        template_elem = None
        for c in root:
            if _tag_name(c) == "template":
                template_elem = c
                break
        template_name = _find_text(template_elem, "name") if template_elem is not None else ""

        regions: list[FlexiPageRegionMetadata] = []
        for reg in root:
            if _tag_name(reg) == "flexiPageRegions":
                reg_name = _find_text(reg, "name") or ""
                reg_type = _find_text(reg, "type") or ""

                components: list[FlexiPageComponentMetadata] = []
                for item in reg:
                    if _tag_name(item) == "itemInstances":
                        for comp in item:
                            if _tag_name(comp) == "componentInstance":
                                c_name = _find_text(comp, "componentName") or ""
                                c_id = _find_text(comp, "identifier") or ""
                                rich_text = None
                                vis_left = None
                                vis_op = None
                                vis_right = None

                                for prop in comp:
                                    if _tag_name(prop) == "componentInstanceProperties":
                                        p_name = _find_text(prop, "name")
                                        if p_name == "richTextValue":
                                            rich_text = _find_text(prop, "value")
                                    elif _tag_name(prop) == "visibilityRule":
                                        for crit in prop:
                                            if _tag_name(crit) == "criteria":
                                                vis_left = _find_text(crit, "leftValue")
                                                vis_op = _find_text(crit, "operator")
                                                vis_right = _find_text(crit, "rightValue")

                                components.append(
                                    FlexiPageComponentMetadata(
                                        component_name=c_name,
                                        identifier=c_id,
                                        rich_text_value=rich_text,
                                        visibility_left_value=vis_left,
                                        visibility_operator=vis_op,
                                        visibility_right_value=vis_right,
                                    )
                                )

                regions.append(
                    FlexiPageRegionMetadata(
                        name=reg_name,
                        region_type=reg_type,
                        components=tuple(components),
                    )
                )

        pages[name] = FlexiPageMetadata(
            name=name,
            master_label=master_label,
            sobject_type=sobject_type,
            template=template_name or "",
            page_type=page_type,
            regions=tuple(regions),
        )

    return pages


def load_salesforce_dx_tabs(tabs_dir: Path) -> dict[str, CustomTabMetadata]:
    """Load CustomTabs from tabs directory."""
    tabs: dict[str, CustomTabMetadata] = {}
    if not tabs_dir.is_dir():
        return tabs

    for p in tabs_dir.glob("*.tab-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".tab-meta", "")
        is_custom_obj = _find_bool(root, "customObject", default=False)
        motif = _find_text(root, "motif")
        desc = _find_text(root, "description")

        tabs[name] = CustomTabMetadata(
            name=name,
            custom_object=is_custom_obj,
            motif=motif,
            description=desc,
        )

    return tabs


def load_salesforce_dx_applications(apps_dir: Path) -> dict[str, CustomApplicationMetadata]:
    """Load CustomApplications from applications directory."""
    apps: dict[str, CustomApplicationMetadata] = {}
    if not apps_dir.is_dir():
        return apps

    for p in apps_dir.glob("*.app-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".app-meta", "")
        label = _find_text(root, "label") or name
        nav_type = _find_text(root, "navType") or "Standard"
        ui_type = _find_text(root, "uiType") or "Lightning"
        desc = _find_text(root, "description")

        form_factors: list[str] = []
        tabs: list[str] = []

        for child in root:
            t = _tag_name(child)
            if t == "formFactors":
                if child.text and child.text.strip():
                    form_factors.append(child.text.strip())
            elif t == "tabs":
                if child.text and child.text.strip():
                    tabs.append(child.text.strip())

        apps[name] = CustomApplicationMetadata(
            name=name,
            label=label,
            form_factors=tuple(form_factors),
            nav_type=nav_type,
            tabs=tuple(tabs),
            ui_type=ui_type,
            description=desc,
        )

    return apps


def load_salesforce_dx_report_types(report_types_dir: Path) -> dict[str, ReportTypeMetadata]:
    """Load ReportTypes from reportTypes directory."""
    types: dict[str, ReportTypeMetadata] = {}
    if not report_types_dir.is_dir():
        return types

    for p in report_types_dir.glob("*.reportType-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".reportType-meta", "")
        label = _find_text(root, "label") or name
        base_obj = _find_text(root, "baseObject") or ""

        outer_join = False
        relationship = None
        for c in root:
            if _tag_name(c) == "join":
                outer_join = _find_bool(c, "outerJoin", default=False)
                relationship = _find_text(c, "relationship")

        sections: list[str] = []
        columns: list[str] = []
        for sec in root:
            if _tag_name(sec) == "sections":
                sec_lbl = _find_text(sec, "masterLabel") or ""
                sections.append(sec_lbl)
                for col in sec:
                    if _tag_name(col) == "columns":
                        fld = _find_text(col, "field")
                        if fld:
                            columns.append(fld)

        types[name] = ReportTypeMetadata(
            name=name,
            label=label,
            base_object=base_obj,
            outer_join=outer_join,
            relationship=relationship,
            sections=tuple(sections),
            columns=tuple(columns),
        )

    return types


def load_salesforce_dx_reports(reports_dir: Path) -> dict[str, ReportMetadata]:
    """Load Reports from reports directory (including subdirectories/folders)."""
    reports: dict[str, ReportMetadata] = {}
    if not reports_dir.is_dir():
        return reports

    for p in reports_dir.rglob("*.report-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        rel_folder = p.parent.name
        report_name = f"{rel_folder}/{p.stem.replace('.report-meta', '')}" if rel_folder != reports_dir.name else p.stem.replace('.report-meta', '')
        label = _find_text(root, "name") or report_name
        report_type = _find_text(root, "reportType") or ""
        report_format = _find_text(root, "format") or "Summary"
        boolean_filter = _find_text(root, "booleanFilter")
        desc = _find_text(root, "description")

        columns: list[str] = []
        groupings_down: list[str] = []
        filters: list[ReportFilterItem] = []

        for child in root:
            t = _tag_name(child)
            if t == "columns":
                fld = _find_text(child, "field")
                if fld:
                    columns.append(fld)
            elif t == "groupingsDown":
                fld = _find_text(child, "field")
                if fld:
                    groupings_down.append(fld)
            elif t == "filter":
                for crit in child:
                    if _tag_name(crit) == "criteriaItems":
                        col = _find_text(crit, "column") or ""
                        op = _find_text(crit, "operator") or "equals"
                        val = _find_text(crit, "value")
                        filters.append(ReportFilterItem(column=col, operator=op, value=val))

        reports[report_name] = ReportMetadata(
            name=report_name,
            label=label,
            report_type=report_type,
            format=report_format,
            columns=tuple(columns),
            groupings_down=tuple(groupings_down),
            boolean_filter=boolean_filter,
            filters=tuple(filters),
            description=desc,
        )

    return reports


def evaluate_list_view_filter(view: ListViewMetadata, record: dict[str, Any], today_date: str) -> bool:
    """Evaluate whether a record matches a list view filter predicate."""
    if not view.filters:
        return True

    results: list[bool] = []
    for f in view.filters:
        val = record.get(f.field)
        val_str = "" if val is None else str(val)

        target_val = f.value if f.value is not None else ""
        if target_val == "TODAY":
            target_val = today_date

        if f.operation == "equals":
            options = [opt.strip() for opt in target_val.split(",")] if target_val else [""]
            results.append(val_str in options)
        elif f.operation == "notEqual":
            results.append(val_str != target_val)
        elif f.operation == "lessOrEqual":
            results.append(bool(val_str and val_str <= target_val))
        elif f.operation == "greaterThan":
            results.append(bool(val_str and val_str > target_val))
        else:
            raise ValueError(f"Unsupported operation: {f.operation}")

    if view.boolean_filter:
        expr = view.boolean_filter.strip()
        for idx in range(len(results), 0, -1):
            expr = expr.replace(str(idx), str(results[idx - 1]))
        expr = expr.replace("AND", "and").replace("OR", "or").replace("NOT", "not")
        return bool(eval(expr, {"__builtins__": None}, {}))
    else:
        return all(results)


def evaluate_report_filter(report: ReportMetadata, record: dict[str, Any]) -> bool:
    """Evaluate whether a record matches a report filter predicate."""
    if not report.filters:
        return True

    results: list[bool] = []
    for f in report.filters:
        field_name = f.column.split(".")[-1]
        val = record.get(field_name)
        val_str = "" if val is None else str(val)
        target_val = f.value if f.value is not None else ""

        if f.operator == "equals":
            options = [opt.strip() for opt in target_val.split(",")] if target_val else [""]
            results.append(val_str in options)
        elif f.operator == "notEqual":
            results.append(val_str != target_val)
        else:
            raise ValueError(f"Unsupported operator: {f.operator}")

    if report.boolean_filter:
        expr = report.boolean_filter.strip()
        for idx in range(len(results), 0, -1):
            expr = expr.replace(str(idx), str(results[idx - 1]))
        expr = expr.replace("AND", "and").replace("OR", "or").replace("NOT", "not")
        return bool(eval(expr, {"__builtins__": None}, {}))
    else:
        return all(results)


def validate_sf03_ui_metadata(sf_main_dir: Path) -> MetadataCompatibilityReport:
    """Validate that all SF-03 UI components exist and satisfy R08 requirements."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Custom Object Job__c compact layout assignment
    job_obj_path = sf_main_dir / "objects" / "Job__c" / "Job__c.object-meta.xml"
    if not job_obj_path.is_file():
        issues.append(f"Job__c object XML not found at {job_obj_path}")
    else:
        tree = ET.parse(job_obj_path)
        cla = _find_text(tree.getroot(), "compactLayoutAssignment")
        if cla != "JA_Tracking":
            issues.append(f"Job__c compactLayoutAssignment must be 'JA_Tracking', got '{cla}'")

    # 2. Compact Layout JA_Tracking
    job_cls = load_salesforce_dx_compact_layouts(sf_main_dir / "objects" / "Job__c")
    if "JA_Tracking" not in job_cls:
        issues.append("CompactLayout 'JA_Tracking' is missing under Job__c/compactLayouts/")
    else:
        cl = job_cls["JA_Tracking"]
        req_cl_fields = {
            "Name",
            "Company__c",
            "Application_Progress__c",
            "Assessment_Disposition__c",
            "Availability__c",
            "Follow_Up_Date__c",
        }
        present_cl_fields = set(cl.fields)
        missing_cl = req_cl_fields - present_cl_fields
        if missing_cl:
            issues.append(f"CompactLayout 'JA_Tracking' missing required fields: {sorted(missing_cl)}")

    # 3. List Views (7 required queues)
    job_views = load_salesforce_dx_list_views(sf_main_dir / "objects" / "Job__c")
    expected_views = {
        "JA_Eligible_Jobs",
        "JA_Review_Jobs",
        "JA_Shortlist",
        "JA_Applications",
        "JA_Follow_Ups_Due",
        "JA_Follow_Ups_Upcoming",
        "JA_Tracked_History",
    }
    missing_views = expected_views - set(job_views.keys())
    if missing_views:
        issues.append(f"Missing required Job__c ListViews: {sorted(missing_views)}")

    for v_name, v_meta in job_views.items():
        if v_name in expected_views:
            if v_meta.filter_scope != "Everything":
                issues.append(f"ListView {v_name} filterScope must be 'Everything' (not 'Mine'), got '{v_meta.filter_scope}'")
            # Verify required columns exist
            for col in ("NAME", "Company__c", "Application_Progress__c", "Assessment_Disposition__c", "Availability__c"):
                if col not in v_meta.columns:
                    issues.append(f"ListView {v_name} missing baseline column '{col}'")

    # 4. Layouts
    layouts = load_salesforce_dx_layouts(sf_main_dir / "layouts")
    if "Job__c-JA Candidate Tracking" not in layouts:
        issues.append("Layout 'Job__c-JA Candidate Tracking' is missing")
    else:
        jl = layouts["Job__c-JA Candidate Tracking"]
        sec_names = [s.label for s in jl.sections]
        for req_sec in ("Your Application", "Machine Assessment", "Posting Availability and Source", "Technical Reference"):
            if req_sec not in sec_names:
                issues.append(f"Job__c layout missing required section: '{req_sec}'")

        # Verify candidate fields are Edit
        cand_fields = {
            "Application_Progress__c",
            "Candidate_Decision__c",
            "Candidate_Notes__c",
            "Follow_Up_Date__c",
            "Interview_Date__c",
        }
        mach_fields = {
            "Assessment_Disposition__c",
            "Relevance_Score__c",
            "Score_Scale__c",
            "Last_Evaluated_At__c",
            "Assessment_Reasons__c",
            "Availability__c",
            "Source_URLs__c",
            "Canonical_Job_Id__c",
            "Machine_Sync_Version__c",
            "Sync_Operation_Marker__c",
        }
        for sec in jl.sections:
            for it in sec.items:
                if it.field in cand_fields:
                    if it.behavior != "Edit":
                        issues.append(f"Candidate field '{it.field}' in layout must have behavior 'Edit', got '{it.behavior}'")
                elif it.field in mach_fields:
                    if it.behavior != "Readonly":
                        issues.append(f"Machine field '{it.field}' in layout must have behavior 'Readonly', got '{it.behavior}'")

    if "Company__c-JA Company Overview" not in layouts:
        issues.append("Layout 'Company__c-JA Company Overview' is missing")
    else:
        cl = layouts["Company__c-JA Company Overview"]
        rel_lists = [r.related_list for r in cl.related_lists]
        if "Job__c.Company__c" not in rel_lists:
            issues.append("Company__c layout missing related list 'Job__c.Company__c'")

    # 5. FlexiPage
    flexipages = load_salesforce_dx_flexipages(sf_main_dir / "flexipages")
    if "JA_Job_Tracking" not in flexipages:
        issues.append("FlexiPage 'JA_Job_Tracking' is missing")
    else:
        fp = flexipages["JA_Job_Tracking"]
        if fp.sobject_type != "Job__c":
            issues.append(f"FlexiPage sobjectType must be 'Job__c', got '{fp.sobject_type}'")
        all_comps = [c for r in fp.regions for c in r.components]
        comp_names = [c.component_name for c in all_comps]
        if "force:highlightsPanel" not in comp_names:
            issues.append("FlexiPage missing force:highlightsPanel")
        if "force:detailPanel" not in comp_names:
            issues.append("FlexiPage missing force:detailPanel")

        # Verify review banner and text guidance
        banner_found = False
        decision_text_found = False
        missing_assessment_banner_found = False
        for c in all_comps:
            if c.rich_text_value:
                if "Review required: eligibility or assessment is unresolved" in c.rich_text_value:
                    banner_found = True
                    if c.visibility_left_value != "{!Record.Assessment_Disposition__c}" or c.visibility_right_value != "Review":
                        issues.append("Review banner has incorrect visibility rule")
                if "Assessment missing" in c.rich_text_value:
                    missing_assessment_banner_found = True
                    if c.visibility_left_value != "{!Record.Assessment_Disposition__c}" or (c.visibility_right_value or "") != "":
                        issues.append("Missing assessment banner has incorrect visibility rule")
                if "Your decision changes your tracking workflow only" in c.rich_text_value:
                    decision_text_found = True

        if not banner_found:
            issues.append("FlexiPage missing review required guidance banner")
        if not missing_assessment_banner_found:
            issues.append("FlexiPage missing assessment missing guidance banner")
        if not decision_text_found:
            issues.append("FlexiPage missing decision guidance text")

    # 6. Tabs
    tabs = load_salesforce_dx_tabs(sf_main_dir / "tabs")
    if "Job__c" not in tabs:
        issues.append("CustomTab 'Job__c' is missing")
    if "Company__c" not in tabs:
        issues.append("CustomTab 'Company__c' is missing")

    # 7. Application
    apps = load_salesforce_dx_applications(sf_main_dir / "applications")
    if "Job_Tracker" not in apps:
        issues.append("CustomApplication 'Job_Tracker' is missing")
    else:
        app = apps["Job_Tracker"]
        if "Job__c" not in app.tabs or "Company__c" not in app.tabs:
            issues.append("CustomApplication 'Job_Tracker' missing Job__c or Company__c tabs")

    # 8. ReportType
    report_types = load_salesforce_dx_report_types(sf_main_dir / "reportTypes")
    if "JA_Jobs" not in report_types:
        issues.append("ReportType 'JA_Jobs' is missing")
    else:
        rt = report_types["JA_Jobs"]
        if rt.base_object != "Job__c":
            issues.append(f"ReportType baseObject must be 'Job__c', got '{rt.base_object}'")
        if not rt.outer_join:
            issues.append("ReportType must configure outerJoin=true on Company__r so jobs without Company are not dropped")

    # 9. Reports
    reports = load_salesforce_dx_reports(sf_main_dir / "reports")
    expected_reports = {
        "Job_Tracker/JA_Eligible_Review",
        "Job_Tracker/JA_Shortlist",
        "Job_Tracker/JA_Applications",
        "Job_Tracker/JA_Follow_Ups",
    }
    missing_reps = expected_reports - set(reports.keys())
    if missing_reps:
        issues.append(f"Missing required Reports under Job_Tracker: {sorted(missing_reps)}")

    for r_name in expected_reports.intersection(set(reports.keys())):
        rep = reports[r_name]
        if rep.report_type != "JA_Jobs":
            issues.append(f"Report {r_name} must use ReportType 'JA_Jobs', got '{rep.report_type}'")
        if rep.format != "Summary":
            issues.append(f"Report {r_name} must have format 'Summary', got '{rep.format}'")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )



def load_external_client_app(
    base_dir: Path, app_name: str
) -> tuple[ExternalClientAppMetadata, EcaOauthSettingsMetadata, EcaOauthPoliciesMetadata]:
    """Load ExternalClientApplication header, OAuth settings, and configurable policies."""
    resolved_base = base_dir.resolve()

    # 1. Header
    header_path = resolved_base / "externalClientApps" / f"{app_name}.eca-meta.xml"
    if not header_path.is_file():
        raise FileNotFoundError(f"ECA header file not found: {header_path}")
    tree_hdr = ET.parse(header_path)
    root_hdr = tree_hdr.getroot()
    app_meta = ExternalClientAppMetadata(
        name=app_name,
        label=_find_text(root_hdr, "label") or app_name,
        contact_email=_find_text(root_hdr, "contactEmail") or "",
        distribution_state=_find_text(root_hdr, "distributionState") or "Local",
        is_protected=_find_bool(root_hdr, "isProtected"),
        description=_find_text(root_hdr, "description"),
    )

    # 2. OAuth Settings
    oauth_path = resolved_base / "extlClntAppOauthSettings" / f"{app_name}.ecaOauth-meta.xml"
    if not oauth_path.is_file():
        raise FileNotFoundError(f"ECA OAuth settings file not found: {oauth_path}")
    tree_oauth = ET.parse(oauth_path)
    root_oauth = tree_oauth.getroot()
    scopes: list[str] = []
    for c in root_oauth:
        if _tag_name(c) == "scopes":
            if c.text and c.text.strip():
                scopes.append(c.text.strip())

    oauth_meta = EcaOauthSettingsMetadata(
        name=app_name,
        external_client_application=_find_text(root_oauth, "externalClientApplication") or app_name,
        label=_find_text(root_oauth, "label") or app_name,
        callback_url=_find_text(root_oauth, "callbackUrl") or "",
        is_pkce_required=_find_bool(root_oauth, "isPkceRequired", default=True),
        is_consumer_secret_optional=_find_bool(root_oauth, "isConsumerSecretOptional", default=False),
        is_secret_required_for_refresh=_find_bool(root_oauth, "isSecretRequiredForRefreshToken", default=False),
        is_introspect_all_tokens=_find_bool(root_oauth, "isIntrospectAllTokens", default=False),
        scopes=tuple(scopes),
    )

    # 3. Configurable Policies
    plcy_path = resolved_base / "extlClntAppOauthPolicies" / f"{app_name}.ecaOauthPlcy-meta.xml"
    if not plcy_path.is_file():
        raise FileNotFoundError(f"ECA OAuth configurable policies file not found: {plcy_path}")
    tree_plcy = ET.parse(plcy_path)
    root_plcy = tree_plcy.getroot()

    validity_period_str = _find_text(root_plcy, "refreshTokenValidityPeriod")
    validity_period = int(validity_period_str) if validity_period_str and validity_period_str.isdigit() else None
    timeout_str = _find_text(root_plcy, "sessionTimeoutInMinutes")
    timeout_mins = int(timeout_str) if timeout_str and timeout_str.isdigit() else None

    policies_meta = EcaOauthPoliciesMetadata(
        name=app_name,
        external_client_application=_find_text(root_plcy, "externalClientApplication") or app_name,
        label=_find_text(root_plcy, "label") or app_name,
        ip_relaxation_policy_type=_find_text(root_plcy, "ipRelaxationPolicyType") or "Enforce",
        permitted_users_policy_type=_find_text(root_plcy, "permittedUsersPolicyType") or "AdminApprovedPreAuthorized",
        refresh_token_policy_type=_find_text(root_plcy, "refreshTokenPolicyType") or "SpecificLifetime",
        refresh_token_validity_period=validity_period,
        refresh_token_validity_unit=_find_text(root_plcy, "refreshTokenValidityUnit") or "Days",
        session_timeout_in_minutes=timeout_mins,
    )

    return app_meta, oauth_meta, policies_meta


def validate_eca_configuration(
    app: ExternalClientAppMetadata,
    oauth: EcaOauthSettingsMetadata,
    policies: EcaOauthPoliciesMetadata,
) -> MetadataCompatibilityReport:
    """Validate that External Client App metadata satisfies SF-02 security and PKCE requirements."""
    issues: list[str] = []
    warnings: list[str] = []

    if app.distribution_state.lower() != "local":
        issues.append(f"ECA distributionState must be 'Local', got '{app.distribution_state}'.")

    if oauth.callback_url != "http://localhost:1717/OauthRedirect":
        issues.append(f"ECA callbackUrl must be 'http://localhost:1717/OauthRedirect', got '{oauth.callback_url}'.")

    if not oauth.is_pkce_required:
        issues.append("ECA isPkceRequired must be True (RFC 7636 PKCE S256 requirement).")

    if not oauth.is_consumer_secret_optional:
        issues.append("ECA isConsumerSecretOptional must be True (secret-free web server flow for installed worker).")

    if oauth.is_secret_required_for_refresh:
        issues.append("ECA isSecretRequiredForRefreshToken must be False (installed worker refresh exchange).")

    normalized_scopes = {s.lower() for s in oauth.scopes}
    if "api" not in normalized_scopes:
        issues.append("ECA scopes must include 'Api'.")
    if "refreshtoken" not in normalized_scopes:
        issues.append("ECA scopes must include 'RefreshToken'.")

    # Forbidden scopes
    forbidden_scopes = {"full", "web", "chatter_api", "custom_permissions"}
    present_forbidden = forbidden_scopes.intersection(normalized_scopes)
    if present_forbidden:
        issues.append(f"ECA requests forbidden broad scopes: {sorted(present_forbidden)}.")

    if policies.permitted_users_policy_type != "AdminApprovedPreAuthorized":
        issues.append(
            f"ECA permittedUsersPolicyType must be 'AdminApprovedPreAuthorized', got '{policies.permitted_users_policy_type}'."
        )

    if policies.ip_relaxation_policy_type.lower() == "relax":
        warnings.append("ECA ipRelaxationPolicyType is set to Relax; Enforce is recommended.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


# ==============================================================================
# SF-03: UI Metadata (ListViews, Layouts, CompactLayouts, Flexipages, Reports)
# ==============================================================================


@dataclass(frozen=True)
class ListViewFilter:
    """Filter condition in a ListView."""

    field: str
    operation: str
    value: str | None


@dataclass(frozen=True)
class ListViewMetadata:
    """Parsed ListView metadata."""

    full_name: str
    label: str
    filter_scope: str
    columns: tuple[str, ...]
    filters: tuple[ListViewFilter, ...] = ()
    boolean_filter: str | None = None


@dataclass(frozen=True)
class CompactLayoutMetadata:
    """Parsed CompactLayout metadata."""

    full_name: str
    label: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LayoutItemMetadata:
    """Field item within a page layout column."""

    field: str
    behavior: str  # "Edit", "Readonly", "Required"


@dataclass(frozen=True)
class LayoutSectionMetadata:
    """Section within a page layout."""

    label: str
    custom_label: bool
    detail_heading: bool
    edit_heading: bool
    style: str
    items: tuple[LayoutItemMetadata, ...]


@dataclass(frozen=True)
class RelatedListMetadata:
    """Related list entry in a page layout."""

    related_list: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LayoutMetadata:
    """Parsed Layout metadata."""

    name: str
    sections: tuple[LayoutSectionMetadata, ...]
    related_lists: tuple[RelatedListMetadata, ...] = ()


@dataclass(frozen=True)
class FlexiPageComponentMetadata:
    """Component instance in a Lightning FlexiPage."""

    component_name: str
    identifier: str
    rich_text_value: str | None = None
    visibility_left_value: str | None = None
    visibility_operator: str | None = None
    visibility_right_value: str | None = None


@dataclass(frozen=True)
class FlexiPageRegionMetadata:
    """Region within a Lightning FlexiPage."""

    name: str
    region_type: str
    components: tuple[FlexiPageComponentMetadata, ...]


@dataclass(frozen=True)
class FlexiPageMetadata:
    """Parsed Lightning FlexiPage record page metadata."""

    name: str
    master_label: str
    sobject_type: str
    template: str
    page_type: str
    regions: tuple[FlexiPageRegionMetadata, ...]


@dataclass(frozen=True)
class CustomTabMetadata:
    """Parsed CustomTab metadata."""

    name: str
    custom_object: bool
    motif: str | None
    description: str | None = None


@dataclass(frozen=True)
class CustomApplicationMetadata:
    """Parsed CustomApplication metadata."""

    name: str
    label: str
    form_factors: tuple[str, ...]
    nav_type: str
    tabs: tuple[str, ...]
    ui_type: str
    description: str | None = None


@dataclass(frozen=True)
class ReportTypeMetadata:
    """Parsed ReportType metadata."""

    name: str
    label: str
    base_object: str
    outer_join: bool
    relationship: str | None
    sections: tuple[str, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ReportFilterItem:
    """Filter criterion in a Report."""

    column: str
    operator: str
    value: str | None


@dataclass(frozen=True)
class ReportMetadata:
    """Parsed Report metadata."""

    name: str
    label: str
    report_type: str
    format: str
    columns: tuple[str, ...]
    groupings_down: tuple[str, ...]
    boolean_filter: str | None = None
    filters: tuple[ReportFilterItem, ...] = ()
    description: str | None = None


def load_salesforce_dx_list_views(object_dir: Path) -> dict[str, ListViewMetadata]:
    """Load all ListViews defined under an object's listViews directory."""
    views_dir = object_dir / "listViews"
    views: dict[str, ListViewMetadata] = {}
    if not views_dir.is_dir():
        return views

    for p in views_dir.glob("*.listView-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        full_name = _find_text(root, "fullName") or p.stem.replace(".listView-meta", "")
        label = _find_text(root, "label") or full_name
        filter_scope = _find_text(root, "filterScope") or "Everything"
        boolean_filter = _find_text(root, "booleanFilter")

        columns: list[str] = []
        filters: list[ListViewFilter] = []

        for child in root:
            t = _tag_name(child)
            if t == "columns":
                if child.text and child.text.strip():
                    columns.append(child.text.strip())
            elif t == "filters":
                field_val = _find_text(child, "field") or ""
                op_val = _find_text(child, "operation") or "equals"
                v_val = _find_text(child, "value")
                filters.append(ListViewFilter(field=field_val, operation=op_val, value=v_val))

        views[full_name] = ListViewMetadata(
            full_name=full_name,
            label=label,
            filter_scope=filter_scope,
            columns=tuple(columns),
            filters=tuple(filters),
            boolean_filter=boolean_filter,
        )

    return views


def load_salesforce_dx_compact_layouts(object_dir: Path) -> dict[str, CompactLayoutMetadata]:
    """Load CompactLayouts defined under an object's compactLayouts directory."""
    cl_dir = object_dir / "compactLayouts"
    cls: dict[str, CompactLayoutMetadata] = {}
    if not cl_dir.is_dir():
        return cls

    for p in cl_dir.glob("*.compactLayout-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        full_name = _find_text(root, "fullName") or p.stem.replace(".compactLayout-meta", "")
        label = _find_text(root, "label") or full_name

        fields: list[str] = []
        for child in root:
            if _tag_name(child) == "fields":
                if child.text and child.text.strip():
                    fields.append(child.text.strip())

        cls[full_name] = CompactLayoutMetadata(
            full_name=full_name,
            label=label,
            fields=tuple(fields),
        )

    return cls


def load_salesforce_dx_layouts(layouts_dir: Path) -> dict[str, LayoutMetadata]:
    """Load page layouts from layouts directory."""
    layouts: dict[str, LayoutMetadata] = {}
    if not layouts_dir.is_dir():
        return layouts

    for p in layouts_dir.glob("*.layout-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".layout-meta", "")

        sections: list[LayoutSectionMetadata] = []
        related_lists: list[RelatedListMetadata] = []

        for child in root:
            t = _tag_name(child)
            if t == "layoutSections":
                sec_label = _find_text(child, "label") or ""
                custom_lbl = _find_bool(child, "customLabel", default=False)
                det_head = _find_bool(child, "detailHeading", default=False)
                edit_head = _find_bool(child, "editHeading", default=False)
                sec_style = _find_text(child, "style") or ""

                items: list[LayoutItemMetadata] = []
                for col in child:
                    if _tag_name(col) == "layoutColumns":
                        for item in col:
                            if _tag_name(item) == "layoutItems":
                                fld = _find_text(item, "field")
                                beh = _find_text(item, "behavior") or "Edit"
                                if fld:
                                    items.append(LayoutItemMetadata(field=fld, behavior=beh))

                sections.append(
                    LayoutSectionMetadata(
                        label=sec_label,
                        custom_label=custom_lbl,
                        detail_heading=det_head,
                        edit_heading=edit_head,
                        style=sec_style,
                        items=tuple(items),
                    )
                )
            elif t == "relatedLists":
                rel_name = _find_text(child, "relatedList") or ""
                rel_fields: list[str] = []
                for sub in child:
                    if _tag_name(sub) == "fields":
                        if sub.text and sub.text.strip():
                            rel_fields.append(sub.text.strip())
                related_lists.append(RelatedListMetadata(related_list=rel_name, fields=tuple(rel_fields)))

        layouts[name] = LayoutMetadata(
            name=name,
            sections=tuple(sections),
            related_lists=tuple(related_lists),
        )

    return layouts


def load_salesforce_dx_flexipages(flexipages_dir: Path) -> dict[str, FlexiPageMetadata]:
    """Load Lightning FlexiPages."""
    pages: dict[str, FlexiPageMetadata] = {}
    if not flexipages_dir.is_dir():
        return pages

    for p in flexipages_dir.glob("*.flexipage-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".flexipage-meta", "")
        master_label = _find_text(root, "masterLabel") or name
        sobject_type = _find_text(root, "sobjectType") or ""
        page_type = _find_text(root, "type") or "RecordPage"

        template_elem = None
        for c in root:
            if _tag_name(c) == "template":
                template_elem = c
                break
        template_name = _find_text(template_elem, "name") if template_elem is not None else ""

        regions: list[FlexiPageRegionMetadata] = []
        for reg in root:
            if _tag_name(reg) == "flexiPageRegions":
                reg_name = _find_text(reg, "name") or ""
                reg_type = _find_text(reg, "type") or ""

                components: list[FlexiPageComponentMetadata] = []
                for item in reg:
                    if _tag_name(item) == "itemInstances":
                        for comp in item:
                            if _tag_name(comp) == "componentInstance":
                                c_name = _find_text(comp, "componentName") or ""
                                c_id = _find_text(comp, "identifier") or ""
                                rich_text = None
                                vis_left = None
                                vis_op = None
                                vis_right = None

                                for prop in comp:
                                    if _tag_name(prop) == "componentInstanceProperties":
                                        p_name = _find_text(prop, "name")
                                        if p_name == "richTextValue":
                                            rich_text = _find_text(prop, "value")
                                    elif _tag_name(prop) == "visibilityRule":
                                        for crit in prop:
                                            if _tag_name(crit) == "criteria":
                                                vis_left = _find_text(crit, "leftValue")
                                                vis_op = _find_text(crit, "operator")
                                                vis_right = _find_text(crit, "rightValue")

                                components.append(
                                    FlexiPageComponentMetadata(
                                        component_name=c_name,
                                        identifier=c_id,
                                        rich_text_value=rich_text,
                                        visibility_left_value=vis_left,
                                        visibility_operator=vis_op,
                                        visibility_right_value=vis_right,
                                    )
                                )

                regions.append(
                    FlexiPageRegionMetadata(
                        name=reg_name,
                        region_type=reg_type,
                        components=tuple(components),
                    )
                )

        pages[name] = FlexiPageMetadata(
            name=name,
            master_label=master_label,
            sobject_type=sobject_type,
            template=template_name or "",
            page_type=page_type,
            regions=tuple(regions),
        )

    return pages


def load_salesforce_dx_tabs(tabs_dir: Path) -> dict[str, CustomTabMetadata]:
    """Load CustomTabs from tabs directory."""
    tabs: dict[str, CustomTabMetadata] = {}
    if not tabs_dir.is_dir():
        return tabs

    for p in tabs_dir.glob("*.tab-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".tab-meta", "")
        is_custom_obj = _find_bool(root, "customObject", default=False)
        motif = _find_text(root, "motif")
        desc = _find_text(root, "description")

        tabs[name] = CustomTabMetadata(
            name=name,
            custom_object=is_custom_obj,
            motif=motif,
            description=desc,
        )

    return tabs


def load_salesforce_dx_applications(apps_dir: Path) -> dict[str, CustomApplicationMetadata]:
    """Load CustomApplications from applications directory."""
    apps: dict[str, CustomApplicationMetadata] = {}
    if not apps_dir.is_dir():
        return apps

    for p in apps_dir.glob("*.app-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".app-meta", "")
        label = _find_text(root, "label") or name
        nav_type = _find_text(root, "navType") or "Standard"
        ui_type = _find_text(root, "uiType") or "Lightning"
        desc = _find_text(root, "description")

        form_factors: list[str] = []
        tabs: list[str] = []

        for child in root:
            t = _tag_name(child)
            if t == "formFactors":
                if child.text and child.text.strip():
                    form_factors.append(child.text.strip())
            elif t == "tabs":
                if child.text and child.text.strip():
                    tabs.append(child.text.strip())

        apps[name] = CustomApplicationMetadata(
            name=name,
            label=label,
            form_factors=tuple(form_factors),
            nav_type=nav_type,
            tabs=tuple(tabs),
            ui_type=ui_type,
            description=desc,
        )

    return apps


def load_salesforce_dx_report_types(report_types_dir: Path) -> dict[str, ReportTypeMetadata]:
    """Load ReportTypes from reportTypes directory."""
    types: dict[str, ReportTypeMetadata] = {}
    if not report_types_dir.is_dir():
        return types

    for p in report_types_dir.glob("*.reportType-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        name = p.stem.replace(".reportType-meta", "")
        label = _find_text(root, "label") or name
        base_obj = _find_text(root, "baseObject") or ""

        outer_join = False
        relationship = None
        for c in root:
            if _tag_name(c) == "join":
                outer_join = _find_bool(c, "outerJoin", default=False)
                relationship = _find_text(c, "relationship")

        sections: list[str] = []
        columns: list[str] = []
        for sec in root:
            if _tag_name(sec) == "sections":
                sec_lbl = _find_text(sec, "masterLabel") or ""
                sections.append(sec_lbl)
                for col in sec:
                    if _tag_name(col) == "columns":
                        fld = _find_text(col, "field")
                        if fld:
                            columns.append(fld)

        types[name] = ReportTypeMetadata(
            name=name,
            label=label,
            base_object=base_obj,
            outer_join=outer_join,
            relationship=relationship,
            sections=tuple(sections),
            columns=tuple(columns),
        )

    return types


def load_salesforce_dx_reports(reports_dir: Path) -> dict[str, ReportMetadata]:
    """Load Reports from reports directory (including subdirectories/folders)."""
    reports: dict[str, ReportMetadata] = {}
    if not reports_dir.is_dir():
        return reports

    for p in reports_dir.rglob("*.report-meta.xml"):
        tree = ET.parse(p)
        root = tree.getroot()
        rel_folder = p.parent.name
        report_name = f"{rel_folder}/{p.stem.replace('.report-meta', '')}" if rel_folder != reports_dir.name else p.stem.replace('.report-meta', '')
        label = _find_text(root, "name") or report_name
        report_type = _find_text(root, "reportType") or ""
        report_format = _find_text(root, "format") or "Summary"
        boolean_filter = _find_text(root, "booleanFilter")
        desc = _find_text(root, "description")

        columns: list[str] = []
        groupings_down: list[str] = []
        filters: list[ReportFilterItem] = []

        for child in root:
            t = _tag_name(child)
            if t == "columns":
                fld = _find_text(child, "field")
                if fld:
                    columns.append(fld)
            elif t == "groupingsDown":
                fld = _find_text(child, "field")
                if fld:
                    groupings_down.append(fld)
            elif t == "filter":
                for crit in child:
                    if _tag_name(crit) == "criteriaItems":
                        col = _find_text(crit, "column") or ""
                        op = _find_text(crit, "operator") or "equals"
                        val = _find_text(crit, "value")
                        filters.append(ReportFilterItem(column=col, operator=op, value=val))

        reports[report_name] = ReportMetadata(
            name=report_name,
            label=label,
            report_type=report_type,
            format=report_format,
            columns=tuple(columns),
            groupings_down=tuple(groupings_down),
            boolean_filter=boolean_filter,
            filters=tuple(filters),
            description=desc,
        )

    return reports


def evaluate_list_view_filter(view: ListViewMetadata, record: dict[str, Any], today_date: str) -> bool:
    """Evaluate whether a record matches a list view filter predicate."""
    if not view.filters:
        return True

    results: list[bool] = []
    for f in view.filters:
        val = record.get(f.field)
        val_str = "" if val is None else str(val)

        target_val = f.value if f.value is not None else ""
        if target_val == "TODAY":
            target_val = today_date

        if f.operation == "equals":
            options = [opt.strip() for opt in target_val.split(",")] if target_val else [""]
            results.append(val_str in options)
        elif f.operation == "notEqual":
            results.append(val_str != target_val)
        elif f.operation == "lessOrEqual":
            results.append(bool(val_str and val_str <= target_val))
        elif f.operation == "greaterThan":
            results.append(bool(val_str and val_str > target_val))
        else:
            raise ValueError(f"Unsupported operation: {f.operation}")

    if view.boolean_filter:
        expr = view.boolean_filter.strip()
        for idx in range(len(results), 0, -1):
            expr = expr.replace(str(idx), str(results[idx - 1]))
        expr = expr.replace("AND", "and").replace("OR", "or").replace("NOT", "not")
        return bool(eval(expr, {"__builtins__": None}, {}))
    else:
        return all(results)


def evaluate_report_filter(report: ReportMetadata, record: dict[str, Any]) -> bool:
    """Evaluate whether a record matches a report filter predicate."""
    if not report.filters:
        return True

    results: list[bool] = []
    for f in report.filters:
        field_name = f.column.split(".")[-1]
        val = record.get(field_name)
        val_str = "" if val is None else str(val)
        target_val = f.value if f.value is not None else ""

        if f.operator == "equals":
            options = [opt.strip() for opt in target_val.split(",")] if target_val else [""]
            results.append(val_str in options)
        elif f.operator == "notEqual":
            results.append(val_str != target_val)
        else:
            raise ValueError(f"Unsupported operator: {f.operator}")

    if report.boolean_filter:
        expr = report.boolean_filter.strip()
        for idx in range(len(results), 0, -1):
            expr = expr.replace(str(idx), str(results[idx - 1]))
        expr = expr.replace("AND", "and").replace("OR", "or").replace("NOT", "not")
        return bool(eval(expr, {"__builtins__": None}, {}))
    else:
        return all(results)


def validate_sf03_ui_metadata(sf_main_dir: Path) -> MetadataCompatibilityReport:
    """Validate that all SF-03 UI components exist and satisfy R08 requirements."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Custom Object Job__c compact layout assignment
    job_obj_path = sf_main_dir / "objects" / "Job__c" / "Job__c.object-meta.xml"
    if not job_obj_path.is_file():
        issues.append(f"Job__c object XML not found at {job_obj_path}")
    else:
        tree = ET.parse(job_obj_path)
        cla = _find_text(tree.getroot(), "compactLayoutAssignment")
        if cla != "JA_Tracking":
            issues.append(f"Job__c compactLayoutAssignment must be 'JA_Tracking', got '{cla}'")

    # 2. Compact Layout JA_Tracking
    job_cls = load_salesforce_dx_compact_layouts(sf_main_dir / "objects" / "Job__c")
    if "JA_Tracking" not in job_cls:
        issues.append("CompactLayout 'JA_Tracking' is missing under Job__c/compactLayouts/")
    else:
        cl = job_cls["JA_Tracking"]
        req_cl_fields = {
            "Name",
            "Company__c",
            "Application_Progress__c",
            "Assessment_Disposition__c",
            "Availability__c",
            "Follow_Up_Date__c",
        }
        present_cl_fields = set(cl.fields)
        missing_cl = req_cl_fields - present_cl_fields
        if missing_cl:
            issues.append(f"CompactLayout 'JA_Tracking' missing required fields: {sorted(missing_cl)}")

    # 3. List Views (7 required queues)
    job_views = load_salesforce_dx_list_views(sf_main_dir / "objects" / "Job__c")
    expected_views = {
        "JA_Eligible_Jobs",
        "JA_Review_Jobs",
        "JA_Shortlist",
        "JA_Applications",
        "JA_Follow_Ups_Due",
        "JA_Follow_Ups_Upcoming",
        "JA_Tracked_History",
    }
    missing_views = expected_views - set(job_views.keys())
    if missing_views:
        issues.append(f"Missing required Job__c ListViews: {sorted(missing_views)}")

    for v_name, v_meta in job_views.items():
        if v_name in expected_views:
            if v_meta.filter_scope != "Everything":
                issues.append(f"ListView {v_name} filterScope must be 'Everything' (not 'Mine'), got '{v_meta.filter_scope}'")
            # Verify required columns exist
            for col in ("NAME", "Company__c", "Application_Progress__c", "Assessment_Disposition__c", "Availability__c"):
                if col not in v_meta.columns:
                    issues.append(f"ListView {v_name} missing baseline column '{col}'")

    # 4. Layouts
    layouts = load_salesforce_dx_layouts(sf_main_dir / "layouts")
    if "Job__c-JA Candidate Tracking" not in layouts:
        issues.append("Layout 'Job__c-JA Candidate Tracking' is missing")
    else:
        jl = layouts["Job__c-JA Candidate Tracking"]
        sec_names = [s.label for s in jl.sections]
        for req_sec in ("Your Application", "Machine Assessment", "Posting Availability and Source", "Technical Reference"):
            if req_sec not in sec_names:
                issues.append(f"Job__c layout missing required section: '{req_sec}'")

        # Verify candidate fields are Edit
        cand_fields = {
            "Application_Progress__c",
            "Candidate_Decision__c",
            "Candidate_Notes__c",
            "Follow_Up_Date__c",
            "Interview_Date__c",
        }
        mach_fields = {
            "Assessment_Disposition__c",
            "Relevance_Score__c",
            "Score_Scale__c",
            "Last_Evaluated_At__c",
            "Assessment_Reasons__c",
            "Availability__c",
            "Source_URLs__c",
            "Canonical_Job_Id__c",
            "Machine_Sync_Version__c",
            "Sync_Operation_Marker__c",
        }
        for sec in jl.sections:
            for it in sec.items:
                if it.field in cand_fields:
                    if it.behavior != "Edit":
                        issues.append(f"Candidate field '{it.field}' in layout must have behavior 'Edit', got '{it.behavior}'")
                elif it.field in mach_fields:
                    if it.behavior != "Readonly":
                        issues.append(f"Machine field '{it.field}' in layout must have behavior 'Readonly', got '{it.behavior}'")

    if "Company__c-JA Company Overview" not in layouts:
        issues.append("Layout 'Company__c-JA Company Overview' is missing")
    else:
        cl = layouts["Company__c-JA Company Overview"]
        rel_lists = [r.related_list for r in cl.related_lists]
        if "Job__c.Company__c" not in rel_lists:
            issues.append("Company__c layout missing related list 'Job__c.Company__c'")

    # 5. FlexiPage
    flexipages = load_salesforce_dx_flexipages(sf_main_dir / "flexipages")
    if "JA_Job_Tracking" not in flexipages:
        issues.append("FlexiPage 'JA_Job_Tracking' is missing")
    else:
        fp = flexipages["JA_Job_Tracking"]
        if fp.sobject_type != "Job__c":
            issues.append(f"FlexiPage sobjectType must be 'Job__c', got '{fp.sobject_type}'")
        all_comps = [c for r in fp.regions for c in r.components]
        comp_names = [c.component_name for c in all_comps]
        if "force:highlightsPanel" not in comp_names:
            issues.append("FlexiPage missing force:highlightsPanel")
        if "force:detailPanel" not in comp_names:
            issues.append("FlexiPage missing force:detailPanel")

        # Verify review banner and text guidance
        banner_found = False
        decision_text_found = False
        missing_assessment_banner_found = False
        for c in all_comps:
            if c.rich_text_value:
                if "Review required: eligibility or assessment is unresolved" in c.rich_text_value:
                    banner_found = True
                    if c.visibility_left_value != "{!Record.Assessment_Disposition__c}" or c.visibility_right_value != "Review":
                        issues.append("Review banner has incorrect visibility rule")
                if "Assessment missing" in c.rich_text_value:
                    missing_assessment_banner_found = True
                    if c.visibility_left_value != "{!Record.Assessment_Disposition__c}" or (c.visibility_right_value or "") != "":
                        issues.append("Missing assessment banner has incorrect visibility rule")
                if "Your decision changes your tracking workflow only" in c.rich_text_value:
                    decision_text_found = True

        if not banner_found:
            issues.append("FlexiPage missing review required guidance banner")
        if not missing_assessment_banner_found:
            issues.append("FlexiPage missing assessment missing guidance banner")
        if not decision_text_found:
            issues.append("FlexiPage missing decision guidance text")

    # 6. Tabs
    tabs = load_salesforce_dx_tabs(sf_main_dir / "tabs")
    if "Job__c" not in tabs:
        issues.append("CustomTab 'Job__c' is missing")
    if "Company__c" not in tabs:
        issues.append("CustomTab 'Company__c' is missing")

    # 7. Application
    apps = load_salesforce_dx_applications(sf_main_dir / "applications")
    if "Job_Tracker" not in apps:
        issues.append("CustomApplication 'Job_Tracker' is missing")
    else:
        app = apps["Job_Tracker"]
        if "Job__c" not in app.tabs or "Company__c" not in app.tabs:
            issues.append("CustomApplication 'Job_Tracker' missing Job__c or Company__c tabs")

    # 8. ReportType
    report_types = load_salesforce_dx_report_types(sf_main_dir / "reportTypes")
    if "JA_Jobs" not in report_types:
        issues.append("ReportType 'JA_Jobs' is missing")
    else:
        rt = report_types["JA_Jobs"]
        if rt.base_object != "Job__c":
            issues.append(f"ReportType baseObject must be 'Job__c', got '{rt.base_object}'")
        if not rt.outer_join:
            issues.append("ReportType must configure outerJoin=true on Company__r so jobs without Company are not dropped")

    # 9. Reports
    reports = load_salesforce_dx_reports(sf_main_dir / "reports")
    expected_reports = {
        "Job_Tracker/JA_Eligible_Review",
        "Job_Tracker/JA_Shortlist",
        "Job_Tracker/JA_Applications",
        "Job_Tracker/JA_Follow_Ups",
    }
    missing_reps = expected_reports - set(reports.keys())
    if missing_reps:
        issues.append(f"Missing required Reports under Job_Tracker: {sorted(missing_reps)}")

    for r_name in expected_reports.intersection(set(reports.keys())):
        rep = reports[r_name]
        if rep.report_type != "JA_Jobs":
            issues.append(f"Report {r_name} must use ReportType 'JA_Jobs', got '{rep.report_type}'")
        if rep.format != "Summary":
            issues.append(f"Report {r_name} must have format 'Summary', got '{rep.format}'")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )




# ==============================================================================
# SF-05: Generation Request Metadata and Requester Access Validation
# ==============================================================================


def validate_generation_request_metadata(
    objects: dict[str, CustomObjectMetadata],
    mapping: Any = None,
) -> MetadataCompatibilityReport:
    """Validate that Salesforce DX metadata for Generation_Request__c satisfies C13 requirements."""
    if mapping is None:
        from job_automation.generation.request_mapping import RequestFieldMapping
        mapping = RequestFieldMapping()

    issues: list[str] = []
    warnings: list[str] = []

    req_obj_name = mapping.request_object.strip().lower()
    if req_obj_name not in objects:
        issues.append(f"Generation Request object '{mapping.request_object}' is missing from metadata.")
        return MetadataCompatibilityReport(compatible=False, issues=tuple(issues), warnings=tuple(warnings))

    req_obj = objects[req_obj_name]

    # Object properties
    if req_obj.sharing_model != "Private":
        issues.append(f"Generation_Request__c sharingModel must be 'Private', got '{req_obj.sharing_model}'.")

    if req_obj.name_field_type != "AutoNumber":
        issues.append(f"Generation_Request__c Name field must be 'AutoNumber', got '{req_obj.name_field_type}'.")
    elif req_obj.name_field_display_format != "GR-{000000}":
        issues.append(f"Generation_Request__c displayFormat must be 'GR-{{000000}}', got '{req_obj.name_field_display_format}'.")

    # Field validations
    fields = req_obj.fields

    # 1. Contract_Schema_Version__c
    f_schema = mapping.schema_version_field.strip().lower()
    if f_schema not in fields:
        issues.append(f"Field '{mapping.schema_version_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_schema]
        if f.field_type != "Text":
            issues.append(f"Field '{mapping.schema_version_field}' must be Text, got '{f.field_type}'.")
        if f.length is not None and f.length < 16:
            issues.append(f"Field '{mapping.schema_version_field}' length {f.length} is too short (min 16).")

    # 2. Client_Request_Key__c
    f_key = mapping.client_key_field.strip().lower()
    if f_key not in fields:
        issues.append(f"Field '{mapping.client_key_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_key]
        if f.field_type != "Text":
            issues.append(f"Field '{mapping.client_key_field}' must be Text, got '{f.field_type}'.")
        if not f.external_id:
            issues.append(f"Field '{mapping.client_key_field}' must be marked as External ID.")
        if not f.unique:
            issues.append(f"Field '{mapping.client_key_field}' must be marked as Unique.")
        if not f.case_sensitive:
            issues.append(f"Field '{mapping.client_key_field}' must be case-sensitive unique.")
        if f.length is not None and f.length < 255:
            issues.append(f"Field '{mapping.client_key_field}' length {f.length} is too short (min 255).")

    # 3. Job__c
    f_job = mapping.job_lookup_field.strip().lower()
    if f_job not in fields:
        issues.append(f"Field '{mapping.job_lookup_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_job]
        if f.field_type != "Lookup":
            issues.append(f"Field '{mapping.job_lookup_field}' must be Lookup, got '{f.field_type}'.")
        if f.reference_to != "Job__c":
            issues.append(f"Field '{mapping.job_lookup_field}' must reference 'Job__c', got '{f.reference_to}'.")
        if f.delete_constraint != "Restrict":
            issues.append(f"Field '{mapping.job_lookup_field}' deleteConstraint must be 'Restrict', got '{f.delete_constraint}'.")

    # 4. Document_Type__c
    f_doc = mapping.document_type_field.strip().lower()
    if f_doc not in fields:
        issues.append(f"Field '{mapping.document_type_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_doc]
        if f.field_type != "Picklist":
            issues.append(f"Field '{mapping.document_type_field}' must be Picklist, got '{f.field_type}'.")
        if not f.restricted_picklist:
            issues.append(f"Field '{mapping.document_type_field}' must be a restricted picklist.")
        required_docs = {"cv", "cover_letter"}
        missing_docs = required_docs - set(f.picklist_values)
        if missing_docs:
            issues.append(f"Field '{mapping.document_type_field}' is missing picklist values: {sorted(missing_docs)}.")

    # 5. Language__c
    f_lang = mapping.target_language_field.strip().lower()
    if f_lang not in fields:
        issues.append(f"Field '{mapping.target_language_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_lang]
        if f.field_type != "Picklist":
            issues.append(f"Field '{mapping.target_language_field}' must be Picklist, got '{f.field_type}'.")
        if not f.restricted_picklist:
            issues.append(f"Field '{mapping.target_language_field}' must be a restricted picklist.")
        required_langs = {"de", "en"}
        missing_langs = required_langs - set(f.picklist_values)
        if missing_langs:
            issues.append(f"Field '{mapping.target_language_field}' is missing picklist values: {sorted(missing_langs)}.")
        if f.default_picklist_value != "de":
            issues.append(f"Field '{mapping.target_language_field}' default value must be 'de', got '{f.default_picklist_value}'.")

    # 6. Template_Id__c
    f_tmpl = mapping.template_id_field.strip().lower()
    if f_tmpl not in fields:
        issues.append(f"Field '{mapping.template_id_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_tmpl]
        if f.field_type != "Text":
            issues.append(f"Field '{mapping.template_id_field}' must be Text, got '{f.field_type}'.")
        if f.length is not None and f.length < 255:
            issues.append(f"Field '{mapping.template_id_field}' length {f.length} is too short (min 255).")

    # 7. Context_Strategy__c
    f_strat = mapping.context_strategy_field.strip().lower()
    if f_strat not in fields:
        issues.append(f"Field '{mapping.context_strategy_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_strat]
        if f.field_type != "Picklist":
            issues.append(f"Field '{mapping.context_strategy_field}' must be Picklist, got '{f.field_type}'.")
        if not f.restricted_picklist:
            issues.append(f"Field '{mapping.context_strategy_field}' must be a restricted picklist.")
        required_strats = {"json", "rag"}
        missing_strats = required_strats - set(f.picklist_values)
        if missing_strats:
            issues.append(f"Field '{mapping.context_strategy_field}' is missing picklist values: {sorted(missing_strats)}.")
        if f.default_picklist_value != "json":
            issues.append(f"Field '{mapping.context_strategy_field}' default value must be 'json', got '{f.default_picklist_value}'.")

    # 8. Allow_Unavailable_Job__c
    f_unavail = mapping.allow_unavailable_field.strip().lower()
    if f_unavail not in fields:
        issues.append(f"Field '{mapping.allow_unavailable_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_unavail]
        if f.field_type != "Checkbox":
            issues.append(f"Field '{mapping.allow_unavailable_field}' must be Checkbox, got '{f.field_type}'.")

    # 9. Predecessor_Request__c
    f_pred = mapping.predecessor_field.strip().lower()
    if f_pred not in fields:
        issues.append(f"Field '{mapping.predecessor_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_pred]
        if f.field_type != "Lookup":
            issues.append(f"Field '{mapping.predecessor_field}' must be Lookup, got '{f.field_type}'.")
        if f.reference_to != "Generation_Request__c":
            issues.append(f"Field '{mapping.predecessor_field}' must reference 'Generation_Request__c', got '{f.reference_to}'.")
        if f.delete_constraint != "Restrict":
            issues.append(f"Field '{mapping.predecessor_field}' deleteConstraint must be 'Restrict', got '{f.delete_constraint}'.")

    # 10. Status__c
    f_status = mapping.status_field.strip().lower()
    if f_status not in fields:
        issues.append(f"Field '{mapping.status_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_status]
        if f.field_type != "Picklist":
            issues.append(f"Field '{mapping.status_field}' must be Picklist, got '{f.field_type}'.")
        if not f.restricted_picklist:
            issues.append(f"Field '{mapping.status_field}' must be a restricted picklist.")
        required_states = {"Pending", "Running", "Upload_Pending", "Ready_for_Review", "Failed"}
        missing_states = required_states - set(f.picklist_values)
        if missing_states:
            issues.append(f"Field '{mapping.status_field}' is missing picklist values: {sorted(missing_states)}.")
        if f.default_picklist_value != "Pending":
            issues.append(f"Field '{mapping.status_field}' default value must be 'Pending', got '{f.default_picklist_value}'.")

    # 11. Timestamps
    for ts_name, ts_role in [
        (mapping.worker_claimed_at_field, "Worker Claimed At"),
        (mapping.completed_at_field, "Completed At"),
    ]:
        k = ts_name.strip().lower()
        if k not in fields:
            issues.append(f"Field '{ts_name}' ({ts_role}) is missing on Generation_Request__c.")
        else:
            f = fields[k]
            if f.field_type != "DateTime":
                issues.append(f"Field '{ts_name}' ({ts_role}) must be DateTime, got '{f.field_type}'.")
            if f.required:
                issues.append(f"Field '{ts_name}' ({ts_role}) must be nullable.")

    # 12. Frozen versions
    for ver_name, ver_role in [
        (mapping.frozen_posting_revision_field, "Frozen Posting Revision"),
        (mapping.frozen_profile_version_field, "Frozen Profile Version"),
        (mapping.frozen_policy_version_field, "Frozen Policy Version"),
        (mapping.frozen_template_version_field, "Frozen Template Version"),
    ]:
        k = ver_name.strip().lower()
        if k not in fields:
            issues.append(f"Field '{ver_name}' ({ver_role}) is missing on Generation_Request__c.")
        else:
            f = fields[k]
            if f.field_type != "Text":
                issues.append(f"Field '{ver_name}' ({ver_role}) must be Text, got '{f.field_type}'.")
            if f.required:
                issues.append(f"Field '{ver_name}' ({ver_role}) must be nullable.")
            if f.length is not None and f.length < 255:
                issues.append(f"Field '{ver_name}' length {f.length} is too short (min 255).")

    # 13. Artifact refs
    for ref_name, ref_role in [
        (mapping.local_artifact_ref_field, "Local Artifact Reference"),
        (mapping.result_artifact_field, "Delivered File Reference"),
    ]:
        k = ref_name.strip().lower()
        if k not in fields:
            issues.append(f"Field '{ref_name}' ({ref_role}) is missing on Generation_Request__c.")
        else:
            f = fields[k]
            if f.field_type != "Text":
                issues.append(f"Field '{ref_name}' ({ref_role}) must be Text, got '{f.field_type}'.")
            if f.required:
                issues.append(f"Field '{ref_name}' ({ref_role}) must be nullable.")
            if f.length is not None and f.length < 255:
                issues.append(f"Field '{ref_name}' length {f.length} is too short (min 255).")

    # 14. Error fields
    f_err_cat = mapping.error_category_field.strip().lower()
    if f_err_cat not in fields:
        issues.append(f"Field '{mapping.error_category_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_err_cat]
        if f.field_type != "Picklist":
            issues.append(f"Field '{mapping.error_category_field}' must be Picklist, got '{f.field_type}'.")
        if not f.restricted_picklist:
            issues.append(f"Field '{mapping.error_category_field}' must be a restricted picklist.")
        from job_automation.contracts.errors import ErrorCategory
        required_cats = {c.value for c in ErrorCategory}
        missing_cats = required_cats - set(f.picklist_values)
        if missing_cats:
            issues.append(f"Field '{mapping.error_category_field}' is missing picklist values: {sorted(missing_cats)}.")

    f_err_reason = mapping.error_reason_field.strip().lower()
    if f_err_reason not in fields:
        issues.append(f"Field '{mapping.error_reason_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_err_reason]
        if f.field_type != "Text":
            issues.append(f"Field '{mapping.error_reason_field}' must be Text, got '{f.field_type}'.")
        if f.required:
            issues.append(f"Field '{mapping.error_reason_field}' must be nullable.")

    f_err_msg = mapping.error_message_field.strip().lower()
    if f_err_msg not in fields:
        issues.append(f"Field '{mapping.error_message_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_err_msg]
        if f.field_type not in ("LongTextArea", "MultiselectPicklist"):
            issues.append(f"Field '{mapping.error_message_field}' must be LongTextArea, got '{f.field_type}'.")
        if f.length is not None and f.length < 2000:
            issues.append(f"Field '{mapping.error_message_field}' length {f.length} is too short (min 2000).")

    f_err_ref = mapping.error_ref_field.strip().lower()
    if f_err_ref not in fields:
        issues.append(f"Field '{mapping.error_ref_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_err_ref]
        if f.field_type != "Text":
            issues.append(f"Field '{mapping.error_ref_field}' must be Text, got '{f.field_type}'.")
        if f.required:
            issues.append(f"Field '{mapping.error_ref_field}' must be nullable.")

    # 15. Operation Marker
    f_marker = mapping.operation_marker_field.strip().lower()
    if f_marker not in fields:
        issues.append(f"Field '{mapping.operation_marker_field}' is missing on Generation_Request__c.")
    else:
        f = fields[f_marker]
        if f.field_type != "Text":
            issues.append(f"Field '{mapping.operation_marker_field}' must be Text, got '{f.field_type}'.")
        if f.required:
            issues.append(f"Field '{mapping.operation_marker_field}' must be nullable.")

    # Validation Rules
    rules = req_obj.validation_rules
    required_rules = {
        "job_required": "Job_Required",
        "template_id_required": "Template_Id_Required",
        "no_self_predecessor": "No_Self_Predecessor",
        "client_request_key_immutable": "Client_Request_Key_Immutable",
        "client_request_key_no_whitespace": "Client_Request_Key_No_Whitespace",
        "immutable_creation_inputs": "Immutable_Creation_Inputs",
        "claim_requires_claimed_at_and_versions": "Claim_Requires_Claimed_At_And_Versions",
        "frozen_versions_immutable": "Frozen_Versions_Immutable",
        "claimed_at_not_before_created": "Claimed_At_Not_Before_Created",
        "completed_at_not_before_created": "Completed_At_Not_Before_Created",
        "completed_at_not_before_claimed": "Completed_At_Not_Before_Claimed",
        "ready_requires_completion_and_result": "Ready_Requires_Completion_And_Result",
        "failed_requires_completion_and_error": "Failed_Requires_Completion_And_Error",
    }

    for rule_key, rule_label in required_rules.items():
        if rule_key not in rules:
            issues.append(f"ValidationRule '{rule_label}' is missing on Generation_Request__c.")
        else:
            r = rules[rule_key]
            if not r.active:
                issues.append(f"ValidationRule '{rule_label}' must be active.")
            if not r.error_condition_formula:
                issues.append(f"ValidationRule '{rule_label}' must have non-empty errorConditionFormula.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_generation_requester_permission_set(
    perm_set: PermissionSetMetadata,
    mapping: Any = None,
) -> MetadataCompatibilityReport:
    """Validate that PermissionSet satisfies Job_Generation_Requester scoped access."""
    if mapping is None:
        from job_automation.generation.request_mapping import RequestFieldMapping
        mapping = RequestFieldMapping()

    issues: list[str] = []
    warnings: list[str] = []

    req_obj = mapping.request_object.strip().lower()

    # 1. Object Permissions
    if req_obj not in perm_set.object_permissions:
        issues.append(f"Requester permission set is missing objectPermissions for '{mapping.request_object}'.")
    else:
        op = perm_set.object_permissions[req_obj]
        if not op.allow_read:
            issues.append(f"Requester must have allowRead on '{mapping.request_object}'.")
        if not op.allow_create:
            issues.append(f"Requester must have allowCreate on '{mapping.request_object}'.")
        if op.allow_edit:
            issues.append(f"Requester must NOT have allowEdit on '{mapping.request_object}' (inputs immutable after create).")
        if op.allow_delete:
            issues.append(f"Requester must NOT have allowDelete on '{mapping.request_object}'.")
        if op.view_all_records:
            issues.append(f"Requester must NOT have viewAllRecords on '{mapping.request_object}'.")
        if op.modify_all_records:
            issues.append(f"Requester must NOT have modifyAllRecords on '{mapping.request_object}'.")

    for parent_obj in ("company__c", "job__c"):
        if parent_obj not in perm_set.object_permissions:
            issues.append(f"Requester permission set must grant objectPermissions for parent '{parent_obj}'.")
        else:
            op = perm_set.object_permissions[parent_obj]
            if not op.allow_read:
                issues.append(f"Requester must have allowRead on parent '{parent_obj}'.")
            if op.allow_create:
                issues.append(f"Requester must NOT have allowCreate on parent '{parent_obj}'.")
            if op.allow_edit:
                issues.append(f"Requester must NOT have allowEdit on parent '{parent_obj}'.")
            if op.allow_delete:
                issues.append(f"Requester must NOT have allowDelete on parent '{parent_obj}'.")

    # 2. Field Permissions - Writable creation inputs
    creation_fields = [
        mapping.job_lookup_field,
        mapping.document_type_field,
        mapping.target_language_field,
        mapping.template_id_field,
        mapping.context_strategy_field,
        mapping.allow_unavailable_field,
        mapping.predecessor_field,
        mapping.schema_version_field,
    ]
    for fld in creation_fields:
        full = f"{req_obj}.{fld.strip().lower()}"
        if full not in perm_set.field_permissions:
            issues.append(f"Missing fieldPermission for creation input '{full}'.")
        else:
            fp = perm_set.field_permissions[full]
            if not fp.readable:
                issues.append(f"Creation input '{full}' must be readable.")
            if not fp.editable:
                issues.append(f"Creation input '{full}' must be editable at creation.")

    # 3. Field Permissions - Read-only worker fields
    worker_fields = [
        mapping.client_key_field,
        mapping.status_field,
        mapping.worker_claimed_at_field,
        mapping.completed_at_field,
        mapping.frozen_posting_revision_field,
        mapping.frozen_profile_version_field,
        mapping.frozen_policy_version_field,
        mapping.frozen_template_version_field,
        mapping.local_artifact_ref_field,
        mapping.result_artifact_field,
        mapping.error_category_field,
        mapping.error_reason_field,
        mapping.error_message_field,
        mapping.error_ref_field,
        mapping.operation_marker_field,
    ]
    for fld in worker_fields:
        full = f"{req_obj}.{fld.strip().lower()}"
        if full not in perm_set.field_permissions:
            issues.append(f"Missing fieldPermission for worker field '{full}'.")
        else:
            fp = perm_set.field_permissions[full]
            if not fp.readable:
                issues.append(f"Worker field '{full}' must be readable by requester.")
            if fp.editable:
                issues.append(f"Worker field '{full}' must NOT be editable by requester.")

    # 4. User permissions
    forbidden_user_perms = {"ModifyAllData", "ViewAllData", "CustomizeApplication", "ManageUsers"}
    present_forbidden = forbidden_user_perms.intersection(perm_set.user_permissions)
    if present_forbidden:
        issues.append(f"Requester permission set grants forbidden administrative userPermissions: {sorted(present_forbidden)}.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


# =============================================================================
# SF-06: Generation Actions, Screen Flows, and Custom Metadata
# =============================================================================

@dataclass(frozen=True)
class QuickActionMetadata:
    """Parsed QuickAction metadata attributes."""

    name: str
    label: str
    action_type: str
    flow_definition: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class FlowMetadata:
    """Parsed Screen Flow metadata attributes."""

    name: str
    label: str
    process_type: str
    status: str
    description: str | None = None
    action_calls: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    variables: tuple[str, ...] = ()


@dataclass(frozen=True)
class CustomMetadataRecord:
    """Parsed CustomMetadata record."""

    name: str
    label: str
    values: dict[str, Any] = field(default_factory=dict)


def load_salesforce_dx_quick_actions(quick_actions_dir: Path) -> dict[str, QuickActionMetadata]:
    """Load and parse QuickAction XML files from salesforce/force-app/main/default/quickActions/."""
    resolved = quick_actions_dir.resolve()
    if not resolved.is_dir():
        return {}

    actions: dict[str, QuickActionMetadata] = {}
    for f in resolved.glob("*.quickAction-meta.xml"):
        tree = ET.parse(f)
        root = tree.getroot()
        action_name = f.stem.replace(".quickAction-meta", "")
        label = _find_text(root, "label") or action_name
        action_type = _find_text(root, "type") or ""
        flow_def = _find_text(root, "flowDefinition")
        desc = _find_text(root, "description")

        actions[action_name.lower()] = QuickActionMetadata(
            name=action_name,
            label=label,
            action_type=action_type,
            flow_definition=flow_def,
            description=desc,
        )
    return actions


def load_salesforce_dx_flows(flows_dir: Path) -> dict[str, FlowMetadata]:
    """Load and parse Flow XML files from salesforce/force-app/main/default/flows/."""
    resolved = flows_dir.resolve()
    if not resolved.is_dir():
        return {}

    flows: dict[str, FlowMetadata] = {}
    for f in resolved.glob("*.flow-meta.xml"):
        tree = ET.parse(f)
        root = tree.getroot()
        flow_name = f.stem.replace(".flow-meta", "")
        label = _find_text(root, "label") or flow_name
        process_type = _find_text(root, "processType") or ""
        status = _find_text(root, "status") or "Draft"
        desc = _find_text(root, "description")

        action_calls: list[str] = []
        screens: list[str] = []
        variables: list[str] = []

        for child in root:
            t = _tag_name(child)
            if t == "actionCalls":
                call_name = _find_text(child, "name")
                if call_name:
                    action_calls.append(call_name)
            elif t == "screens":
                scr_name = _find_text(child, "name")
                if scr_name:
                    screens.append(scr_name)
            elif t == "variables":
                var_name = _find_text(child, "name")
                if var_name:
                    variables.append(var_name)

        flows[flow_name.lower()] = FlowMetadata(
            name=flow_name,
            label=label,
            process_type=process_type,
            status=status,
            description=desc,
            action_calls=tuple(action_calls),
            screens=tuple(screens),
            variables=tuple(variables),
        )
    return flows


def load_salesforce_dx_custom_metadata(custom_metadata_dir: Path) -> dict[str, CustomMetadataRecord]:
    """Load and parse CustomMetadata records from salesforce/force-app/main/default/customMetadata/."""
    resolved = custom_metadata_dir.resolve()
    if not resolved.is_dir():
        return {}

    records: dict[str, CustomMetadataRecord] = {}
    for f in resolved.glob("*.md-meta.xml"):
        tree = ET.parse(f)
        root = tree.getroot()
        rec_name = f.stem.replace(".md-meta", "")
        label = _find_text(root, "label") or rec_name

        vals: dict[str, Any] = {}
        for child in root:
            if _tag_name(child) == "values":
                field_elem = None
                val_elem = None
                for sub in child:
                    sub_tag = _tag_name(sub)
                    if sub_tag == "field":
                        field_elem = sub.text
                    elif sub_tag == "value":
                        val_elem = sub.text

                if field_elem:
                    vals[field_elem.lower()] = val_elem

        records[rec_name.lower()] = CustomMetadataRecord(
            name=rec_name,
            label=label,
            values=vals,
        )
    return records


def validate_sf06_metadata(
    objects: dict[str, CustomObjectMetadata],
    flows: dict[str, FlowMetadata],
    quick_actions: dict[str, QuickActionMetadata],
    options: dict[str, CustomMetadataRecord],
) -> MetadataCompatibilityReport:
    """Validate that SF-06 generation actions, flows, receipts, and custom metadata meet platform requirements."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. JA_Generation_Submission__c Object
    sub_key = "ja_generation_submission__c"
    if sub_key not in objects:
        issues.append("CustomObject 'JA_Generation_Submission__c' is missing.")
    else:
        obj = objects[sub_key]
        if obj.sharing_model != "Private":
            issues.append(f"JA_Generation_Submission__c sharingModel must be 'Private', got '{obj.sharing_model}'.")
        if obj.name_field_type != "AutoNumber":
            issues.append(f"JA_Generation_Submission__c Name field must be AutoNumber, got '{obj.name_field_type}'.")
        if obj.name_field_display_format != "GS-{000000}":
            issues.append(f"JA_Generation_Submission__c Name displayFormat must be 'GS-{{000000}}', got '{obj.name_field_display_format}'.")

        # Validate required fields on JA_Generation_Submission__c
        expected_fields = {
            "submission_key__c": ("Text", True, True, True),  # (type, external_id, unique, case_sensitive)
            "payload_version__c": ("Text", False, False, False),
            "intent_payload__c": ("LongTextArea", False, False, False),
            "request__c": ("Lookup", False, False, False),
            "outcome__c": ("Text", False, False, False),
        }
        for fname, (ftype, ext_id, uniq, cs) in expected_fields.items():
            if fname not in obj.fields:
                issues.append(f"Field '{fname}' is missing on JA_Generation_Submission__c.")
            else:
                fld = obj.fields[fname]
                if fld.field_type != ftype:
                    issues.append(f"Field '{fname}' must be '{ftype}', got '{fld.field_type}'.")
                if ext_id and not fld.external_id:
                    issues.append(f"Field '{fname}' must be an External ID.")
                if uniq and not fld.unique:
                    issues.append(f"Field '{fname}' must be Unique.")
                if cs and not fld.case_sensitive:
                    issues.append(f"Field '{fname}' must be Case Sensitive.")
                if fname == "request__c" and fld.delete_constraint != "Restrict":
                    issues.append(f"Field 'Request__c' deleteConstraint must be 'Restrict', got '{fld.delete_constraint}'.")

    # 2. JA_Generation_Option__mdt Custom Metadata Object
    opt_key = "ja_generation_option__mdt"
    if opt_key not in objects:
        issues.append("CustomObject 'JA_Generation_Option__mdt' is missing.")
    else:
        obj = objects[opt_key]
        if obj.visibility != "Public":
            issues.append(f"JA_Generation_Option__mdt visibility must be 'Public', got '{obj.visibility}'.")

        opt_expected_fields = [
            "template_id__c",
            "document_type__c",
            "allowed_languages__c",
            "is_enabled__c",
            "catalog_version__c",
            "sort_order__c",
        ]
        for fname in opt_expected_fields:
            if fname not in obj.fields:
                issues.append(f"Field '{fname}' is missing on JA_Generation_Option__mdt.")

    # 3. Flows
    if "ja_generate_cv" not in flows:
        issues.append("Flow 'JA_Generate_CV' is missing.")
    else:
        fl = flows["ja_generate_cv"]
        if fl.status != "Active":
            issues.append(f"Flow 'JA_Generate_CV' status must be 'Active', got '{fl.status}'.")
        if fl.process_type != "Flow":
            issues.append(f"Flow 'JA_Generate_CV' processType must be 'Flow', got '{fl.process_type}'.")
        if "recordId" not in fl.variables:
            issues.append("Flow 'JA_Generate_CV' must declare input variable 'recordId'.")
        if "Submit_Generation_Request" not in fl.action_calls:
            issues.append("Flow 'JA_Generate_CV' must invoke Apex action 'Submit_Generation_Request'.")

    if "ja_generate_cover_letter" not in flows:
        issues.append("Flow 'JA_Generate_Cover_Letter' is missing.")
    else:
        fl = flows["ja_generate_cover_letter"]
        if fl.status != "Active":
            issues.append(f"Flow 'JA_Generate_Cover_Letter' status must be 'Active', got '{fl.status}'.")
        if fl.process_type != "Flow":
            issues.append(f"Flow 'JA_Generate_Cover_Letter' processType must be 'Flow', got '{fl.process_type}'.")
        if "recordId" not in fl.variables:
            issues.append("Flow 'JA_Generate_Cover_Letter' must declare input variable 'recordId'.")
        if "Submit_Generation_Request" not in fl.action_calls:
            issues.append("Flow 'JA_Generate_Cover_Letter' must invoke Apex action 'Submit_Generation_Request'.")

    # 4. QuickActions
    if "job__c.ja_generate_cv" not in quick_actions:
        issues.append("QuickAction 'Job__c.JA_Generate_CV' is missing.")
    else:
        qa = quick_actions["job__c.ja_generate_cv"]
        if qa.action_type != "Flow":
            issues.append(f"QuickAction 'Job__c.JA_Generate_CV' type must be 'Flow', got '{qa.action_type}'.")
        if qa.flow_definition != "JA_Generate_CV":
            issues.append(f"QuickAction 'Job__c.JA_Generate_CV' flowDefinition must be 'JA_Generate_CV', got '{qa.flow_definition}'.")

    if "job__c.ja_generate_cover_letter" not in quick_actions:
        issues.append("QuickAction 'Job__c.JA_Generate_Cover_Letter' is missing.")
    else:
        qa = quick_actions["job__c.ja_generate_cover_letter"]
        if qa.action_type != "Flow":
            issues.append(f"QuickAction 'Job__c.JA_Generate_Cover_Letter' type must be 'Flow', got '{qa.action_type}'.")
        if qa.flow_definition != "JA_Generate_Cover_Letter":
            issues.append(f"QuickAction 'Job__c.JA_Generate_Cover_Letter' flowDefinition must be 'JA_Generate_Cover_Letter', got '{qa.flow_definition}'.")

    # 5. Custom Metadata Records (Catalog Options)
    required_options = {
        "ja_generation_option.cv_basic_a4": ("layout-cv-basic-a4", "cv"),
        "ja_generation_option.cv_compact_a4": ("layout-cv-compact-a4", "cv"),
        "ja_generation_option.letter_basic_a4": ("layout-letter-basic-a4", "cover_letter"),
        "ja_generation_option.letter_compact_a4": ("layout-letter-compact-a4", "cover_letter"),
    }
    for opt_name, (expected_tmpl, expected_doc) in required_options.items():
        if opt_name not in options:
            issues.append(f"Catalog record '{opt_name}' is missing.")
        else:
            rec = options[opt_name]
            tmpl = rec.values.get("template_id__c")
            dtype = rec.values.get("document_type__c")
            enabled = rec.values.get("is_enabled__c")
            langs = rec.values.get("allowed_languages__c", "")

            if tmpl != expected_tmpl:
                issues.append(f"Option '{opt_name}' template_id must be '{expected_tmpl}', got '{tmpl}'.")
            if dtype != expected_doc:
                issues.append(f"Option '{opt_name}' document_type must be '{expected_doc}', got '{dtype}'.")
            if enabled != "true":
                issues.append(f"Option '{opt_name}' must be enabled.")
            if "de" not in langs or "en" not in langs:
                issues.append(f"Option '{opt_name}' must support languages 'de' and 'en'.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_sf06_actions_permission_set(
    perm_set: PermissionSetMetadata,
) -> MetadataCompatibilityReport:
    """Validate that Job_Generation_Actions PermissionSet grants correct action/flow execution rights and scoped data access."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Apex Class Access
    if "ja_generationsubmit" not in perm_set.class_accesses or not perm_set.class_accesses["ja_generationsubmit"]:
        issues.append("Permission set must grant enabled classAccess for 'JA_GenerationSubmit'.")

    # 2. Flow Access
    if "ja_generate_cv" not in perm_set.flow_accesses or not perm_set.flow_accesses["ja_generate_cv"]:
        issues.append("Permission set must grant enabled flowAccess for 'JA_Generate_CV'.")
    if "ja_generate_cover_letter" not in perm_set.flow_accesses or not perm_set.flow_accesses["ja_generate_cover_letter"]:
        issues.append("Permission set must grant enabled flowAccess for 'JA_Generate_Cover_Letter'.")

    # 3. Object Permissions
    # JA_Generation_Submission__c: Read, Create (no Edit, no Delete)
    sub_key = "ja_generation_submission__c"
    if sub_key not in perm_set.object_permissions:
        issues.append(f"Missing objectPermissions for '{sub_key}'.")
    else:
        op = perm_set.object_permissions[sub_key]
        if not op.allow_read:
            issues.append(f"Must have allowRead on '{sub_key}'.")
        if not op.allow_create:
            issues.append(f"Must have allowCreate on '{sub_key}'.")
        if op.allow_edit:
            issues.append(f"Must NOT have allowEdit on '{sub_key}'.")
        if op.allow_delete:
            issues.append(f"Must NOT have allowDelete on '{sub_key}'.")

    # Generation_Request__c: Read, Create (no Edit, no Delete)
    req_key = "generation_request__c"
    if req_key not in perm_set.object_permissions:
        issues.append(f"Missing objectPermissions for '{req_key}'.")
    else:
        op = perm_set.object_permissions[req_key]
        if not op.allow_read:
            issues.append(f"Must have allowRead on '{req_key}'.")
        if not op.allow_create:
            issues.append(f"Must have allowCreate on '{req_key}'.")
        if op.allow_edit:
            issues.append(f"Must NOT have allowEdit on '{req_key}'.")
        if op.allow_delete:
            issues.append(f"Must NOT have allowDelete on '{req_key}'.")

    # 4. Field Permissions on JA_Generation_Submission__c
    sub_fields = [
        "submission_key__c",
        "payload_version__c",
        "intent_payload__c",
        "request__c",
        "outcome__c",
    ]
    for sf in sub_fields:
        full = f"{sub_key}.{sf}"
        if full not in perm_set.field_permissions:
            issues.append(f"Missing fieldPermission for '{full}'.")
        else:
            fp = perm_set.field_permissions[full]
            if not fp.readable:
                issues.append(f"Field '{full}' must be readable.")
            if not fp.editable:
                issues.append(f"Field '{full}' must be editable.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class LwcMetadata:
    """Parsed Lightning Web Component bundle metadata."""
    name: str
    master_label: str
    is_exposed: bool
    targets: tuple[str, ...]
    target_objects: tuple[str, ...]


@dataclass(frozen=True)
class CustomPermissionMetadata:
    """Parsed CustomPermission metadata."""
    name: str
    label: str
    description: str | None = None


def load_salesforce_dx_lwc(lwc_dir: Path) -> dict[str, LwcMetadata]:
    """Load and parse LWC bundle metadata from lwc directory."""
    result: dict[str, LwcMetadata] = {}
    if not lwc_dir.exists():
        return result

    for bundle_dir in lwc_dir.iterdir():
        if not bundle_dir.is_dir():
            continue
        meta_xml = bundle_dir / f"{bundle_dir.name}.js-meta.xml"
        if not meta_xml.exists():
            continue

        try:
            tree = ET.parse(meta_xml)
            root = tree.getroot()
            master_label = _find_text(root, "masterLabel") or bundle_dir.name
            is_exposed = _find_bool(root, "isExposed")

            targets: list[str] = []
            targets_elem = root.find(f"{SF_NS}targets")
            if targets_elem is not None:
                for t_node in targets_elem.findall(f"{SF_NS}target"):
                    if t_node.text:
                        targets.append(t_node.text.strip())

            target_objects: list[str] = []
            configs_elem = root.find(f"{SF_NS}targetConfigs")
            if configs_elem is not None:
                for obj_node in configs_elem.findall(f".//{SF_NS}object"):
                    if obj_node.text:
                        target_objects.append(obj_node.text.strip())

            result[bundle_dir.name.lower()] = LwcMetadata(
                name=bundle_dir.name,
                master_label=master_label,
                is_exposed=is_exposed,
                targets=tuple(targets),
                target_objects=tuple(target_objects),
            )
        except Exception:
            continue

    return result


def load_salesforce_dx_custom_permissions(perm_dir: Path) -> dict[str, CustomPermissionMetadata]:
    """Load and parse CustomPermission metadata files."""
    result: dict[str, CustomPermissionMetadata] = {}
    if not perm_dir.exists():
        return result

    for perm_file in perm_dir.glob("*.customPermission-meta.xml"):
        try:
            tree = ET.parse(perm_file)
            root = tree.getroot()
            name = perm_file.name.replace(".customPermission-meta.xml", "")
            label = _find_text(root, "label") or name
            desc = _find_text(root, "description")
            result[name.lower()] = CustomPermissionMetadata(
                name=name,
                label=label,
                description=desc,
            )
        except Exception:
            continue

    return result


def validate_sf07_metadata(
    objects: dict[str, CustomObjectMetadata],
    perm_sets: dict[str, PermissionSetMetadata],
    lwcs: dict[str, LwcMetadata],
    flexipages: dict[str, FlexiPageMetadata],
    custom_perms: dict[str, CustomPermissionMetadata] | None = None,
) -> MetadataCompatibilityReport:
    """Validate SF-07 review objects, permissions, LWC, and FlexiPage metadata."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. JA_Artifact_Review__c Object
    rev_key = "ja_artifact_review__c"
    if rev_key not in objects:
        issues.append("CustomObject 'JA_Artifact_Review__c' is missing.")
    else:
        obj = objects[rev_key]
        if obj.sharing_model != "Private":
            issues.append(f"JA_Artifact_Review__c sharingModel must be 'Private', got '{obj.sharing_model}'.")
        if obj.name_field_type != "AutoNumber":
            issues.append(f"JA_Artifact_Review__c Name field must be AutoNumber, got '{obj.name_field_type}'.")
        if obj.name_field_display_format != "AR-{000000}":
            issues.append(f"JA_Artifact_Review__c Name displayFormat must be 'AR-{{000000}}', got '{obj.name_field_display_format}'.")

        expected_fields = {
            "binding_key__c": ("Text", True, True, True),
            "contract_schema_version__c": ("Text", False, False, False),
            "generation_request__c": ("Lookup", False, False, False),
            "org_id__c": ("Text", False, False, False),
            "artifact_set_id__c": ("Text", False, False, False),
            "artifact_id__c": ("Text", False, False, False),
            "artifact_version__c": ("Number", False, False, False),
            "format__c": ("Picklist", False, False, False),
            "content_hash__c": ("Text", False, False, False),
            "size_bytes__c": ("Number", False, False, False),
            "content_document_id__c": ("Text", False, False, False),
            "content_version_id__c": ("Text", False, False, False),
            "reconciliation_marker__c": ("Text", False, False, False),
            "delivery_receipt_ref__c": ("Text", False, False, False),
            "delivered_at__c": ("DateTime", False, False, False),
            "safe_warnings__c": ("LongTextArea", False, False, False),
            "predecessor_binding__c": ("Lookup", False, False, False),
            "approval_status__c": ("Picklist", False, False, False),
            "review_revision__c": ("Number", False, False, False),
            "approved_by__c": ("Text", False, False, False),
            "approved_at__c": ("DateTime", False, False, False),
            "approval_event_ref__c": ("Text", False, False, False),
            "superseded_by__c": ("Lookup", False, False, False),
            "superseded_at__c": ("DateTime", False, False, False),
        }

        for fname, (ftype, ext_id, uniq, cs) in expected_fields.items():
            if fname not in obj.fields:
                issues.append(f"Field '{fname}' is missing on JA_Artifact_Review__c.")
            else:
                fld = obj.fields[fname]
                if fld.field_type != ftype:
                    issues.append(f"Field '{fname}' on JA_Artifact_Review__c must be '{ftype}', got '{fld.field_type}'.")
                if ext_id and not fld.external_id:
                    issues.append(f"Field '{fname}' must be an External ID.")
                if uniq and not fld.unique:
                    issues.append(f"Field '{fname}' must be Unique.")
                if cs and not fld.case_sensitive:
                    issues.append(f"Field '{fname}' must be Case Sensitive.")
                if fname == "generation_request__c" and fld.delete_constraint != "Restrict":
                    issues.append(f"Field 'Generation_Request__c' deleteConstraint must be 'Restrict', got '{fld.delete_constraint}'.")

        # Check validation rules
        val_rules = obj.validation_rules
        if "immutable_binding_fields" not in val_rules:
            issues.append("Validation rule 'Immutable_Binding_Fields' is missing on JA_Artifact_Review__c.")
        if "approved_requires_actor_and_timestamp" not in val_rules:
            issues.append("Validation rule 'Approved_Requires_Actor_And_Timestamp' is missing on JA_Artifact_Review__c.")
        if "superseded_requires_timestamp" not in val_rules:
            issues.append("Validation rule 'Superseded_Requires_Timestamp' is missing on JA_Artifact_Review__c.")

    # 2. JA_Artifact_Review_Event__c Object
    event_key = "ja_artifact_review_event__c"
    if event_key not in objects:
        issues.append("CustomObject 'JA_Artifact_Review_Event__c' is missing.")
    else:
        obj = objects[event_key]
        if obj.sharing_model != "Private":
            issues.append(f"JA_Artifact_Review_Event__c sharingModel must be 'Private', got '{obj.sharing_model}'.")
        if obj.name_field_type != "AutoNumber":
            issues.append(f"JA_Artifact_Review_Event__c Name field must be AutoNumber, got '{obj.name_field_type}'.")
        if obj.name_field_display_format != "ARE-{000000}":
            issues.append(f"JA_Artifact_Review_Event__c Name displayFormat must be 'ARE-{{000000}}', got '{obj.name_field_display_format}'.")

        expected_event_fields = {
            "event_key__c": ("Text", True, True, True),
            "artifact_review__c": ("Lookup", False, False, False),
            "action__c": ("Picklist", False, False, False),
            "previous_status__c": ("Text", False, False, False),
            "new_status__c": ("Text", False, False, False),
            "prior_review_revision__c": ("Number", False, False, False),
            "new_review_revision__c": ("Number", False, False, False),
            "actor__c": ("Text", False, False, False),
            "event_timestamp__c": ("DateTime", False, False, False),
            "selected_content_version_id__c": ("Text", False, False, False),
            "selected_content_hash__c": ("Text", False, False, False),
            "replaced_artifact_review__c": ("Lookup", False, False, False),
            "candidate_notes__c": ("LongTextArea", False, False, False),
        }

        for fname, (ftype, ext_id, uniq, cs) in expected_event_fields.items():
            if fname not in obj.fields:
                issues.append(f"Field '{fname}' is missing on JA_Artifact_Review_Event__c.")
            else:
                fld = obj.fields[fname]
                if fld.field_type != ftype:
                    issues.append(f"Field '{fname}' on JA_Artifact_Review_Event__c must be '{ftype}', got '{fld.field_type}'.")
                if ext_id and not fld.external_id:
                    issues.append(f"Field '{fname}' must be an External ID.")
                if uniq and not fld.unique:
                    issues.append(f"Field '{fname}' must be Unique.")
                if cs and not fld.case_sensitive:
                    issues.append(f"Field '{fname}' must be Case Sensitive.")
                if fname == "artifact_review__c" and fld.delete_constraint != "Restrict":
                    issues.append(f"Field 'Artifact_Review__c' deleteConstraint must be 'Restrict', got '{fld.delete_constraint}'.")

    # 3. LWC Component jaArtifactReview
    if "jaartifactreview" not in lwcs:
        issues.append("LWC component 'jaArtifactReview' is missing.")
    else:
        comp = lwcs["jaartifactreview"]
        if not comp.is_exposed:
            issues.append("LWC 'jaArtifactReview' must have isExposed=True.")
        if "lightning__RecordPage" not in comp.targets:
            issues.append("LWC 'jaArtifactReview' must include target 'lightning__RecordPage'.")
        if "Generation_Request__c" not in comp.target_objects:
            issues.append("LWC 'jaArtifactReview' targetConfigs must include 'Generation_Request__c'.")

    # 4. FlexiPage JA_Generation_Request_Review
    fp_matches = [fp for k, fp in flexipages.items() if k.lower() == "ja_generation_request_review"]
    if not fp_matches:
        issues.append("FlexiPage 'JA_Generation_Request_Review' is missing.")
    else:
        fp = fp_matches[0]
        if fp.sobject_type != "Generation_Request__c":
            issues.append(f"FlexiPage 'JA_Generation_Request_Review' sobjectType must be 'Generation_Request__c', got '{fp.sobject_type}'.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_sf07_reviewer_permission_set(
    perm_set: PermissionSetMetadata,
) -> MetadataCompatibilityReport:
    """Validate that Job_Document_Reviewer PermissionSet grants candidate review authority with least privilege."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Custom Permission
    if "ja_review_generated_documents" not in perm_set.custom_permissions or not perm_set.custom_permissions["ja_review_generated_documents"]:
        issues.append("Permission set must grant enabled customPermission for 'JA_Review_Generated_Documents'.")

    # 2. Apex Class Access
    if "ja_artifactreviewservice" not in perm_set.class_accesses or not perm_set.class_accesses["ja_artifactreviewservice"]:
        issues.append("Permission set must grant enabled classAccess for 'JA_ArtifactReviewService'.")

    # 3. Object Permissions: Read-only on JA_Artifact_Review__c & JA_Artifact_Review_Event__c
    for obj_name in ("ja_artifact_review__c", "ja_artifact_review_event__c"):
        if obj_name not in perm_set.object_permissions:
            issues.append(f"Missing objectPermissions for '{obj_name}'.")
        else:
            op = perm_set.object_permissions[obj_name]
            if not op.allow_read:
                issues.append(f"Must grant allowRead on '{obj_name}'.")
            if op.allow_create:
                issues.append(f"Must NOT grant allowCreate on '{obj_name}' (candidate review records are created by worker registration).")
            if op.allow_edit:
                issues.append(f"Must NOT grant allowEdit on '{obj_name}' (state changes must occur via service only).")
            if op.allow_delete:
                issues.append(f"Must NOT grant allowDelete on '{obj_name}' (audit preservation).")

    # 4. Field Permissions: Read-only on review records
    if "ja_artifact_review__c.approval_status__c" in perm_set.field_permissions:
        fp = perm_set.field_permissions["ja_artifact_review__c.approval_status__c"]
        if fp.editable:
            issues.append("Approval_Status__c must NOT be directly editable by candidate (must use service).")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


# =============================================================================
# SF-08: Notification Types, Notification Flows, Config & Ledger Metadata
# =============================================================================

@dataclass(frozen=True)
class CustomNotificationTypeMetadata:
    """Parsed CustomNotificationType metadata attributes (SF-08)."""

    name: str
    custom_notif_type_name: str
    description: str | None = None
    desktop: bool = True
    mobile: bool = False


def load_salesforce_dx_notification_types(
    notif_types_dir: Path,
) -> dict[str, CustomNotificationTypeMetadata]:
    """Load and parse CustomNotificationType XML files from notificationtypes/."""
    resolved = notif_types_dir.resolve()
    if not resolved.is_dir():
        return {}
    results: dict[str, CustomNotificationTypeMetadata] = {}
    for f in resolved.glob("*.notiftype-meta.xml"):
        tree = ET.parse(f)
        root = tree.getroot()
        name = f.stem.replace(".notiftype-meta", "")
        custom_notif_type_name = _find_text(root, "customNotifTypeName") or name
        desc = _find_text(root, "description")
        desktop = _find_bool(root, "desktop", default=True)
        mobile = _find_bool(root, "mobile", default=False)
        results[name.lower()] = CustomNotificationTypeMetadata(
            name=name,
            custom_notif_type_name=custom_notif_type_name,
            description=desc,
            desktop=desktop,
            mobile=mobile,
        )
    return results


def validate_sf08_metadata(
    objects: dict[str, CustomObjectMetadata],
    perm_sets: dict[str, PermissionSetMetadata],
    flows: dict[str, FlowMetadata],
    notif_types: dict[str, CustomNotificationTypeMetadata],
    custom_perms: dict[str, CustomPermissionMetadata] | None = None,
) -> MetadataCompatibilityReport:
    """Validate SF-08 notification types, flows, custom objects, and permissions."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Custom Notification Types
    for expected_type in ("ja_draft_ready", "ja_request_action_required"):
        if expected_type not in notif_types:
            issues.append(f"CustomNotificationType '{expected_type}' is missing.")
        else:
            nt = notif_types[expected_type]
            if not nt.desktop:
                issues.append(f"CustomNotificationType '{expected_type}' must have desktop=true.")
            if nt.mobile:
                issues.append(f"CustomNotificationType '{expected_type}' mobile must default to false.")

    # 2. JA_Notification_Config__c Object
    cfg_key = "ja_notification_config__c"
    if cfg_key not in objects:
        issues.append("CustomObject 'JA_Notification_Config__c' is missing.")
    else:
        cfg_obj = objects[cfg_key]
        if cfg_obj.sharing_model != "Private":
            issues.append(f"JA_Notification_Config__c sharingModel must be 'Private', got '{cfg_obj.sharing_model}'.")
        if cfg_obj.name_field_type != "AutoNumber":
            issues.append(f"JA_Notification_Config__c Name must be AutoNumber, got '{cfg_obj.name_field_type}'.")

        expected_cfg_fields = {
            "is_enabled__c": "Checkbox",
            "candidate_user__c": "Lookup",
            "permitted_event_kinds__c": "Text",
            "preferred_language__c": "Picklist",
            "enable_mobile__c": "Checkbox",
            "max_retry_attempts__c": "Number",
            "initial_retry_delay_minutes__c": "Number",
            "activation_watermark__c": "DateTime",
            "org_key__c": "Text",
        }
        for fname, ftype in expected_cfg_fields.items():
            if fname not in cfg_obj.fields:
                issues.append(f"Field '{fname}' is missing on JA_Notification_Config__c.")
            elif cfg_obj.fields[fname].field_type != ftype:
                issues.append(f"Field '{fname}' on JA_Notification_Config__c must be '{ftype}', got '{cfg_obj.fields[fname].field_type}'.")

        if "org_key__c" in cfg_obj.fields:
            ok_fld = cfg_obj.fields["org_key__c"]
            if not ok_fld.external_id:
                issues.append("Field 'Org_Key__c' on JA_Notification_Config__c must be an External ID.")
            if not ok_fld.unique:
                issues.append("Field 'Org_Key__c' on JA_Notification_Config__c must be Unique.")

        if "enabled_requires_candidate" not in cfg_obj.validation_rules:
            issues.append("Validation rule 'Enabled_Requires_Candidate' is missing on JA_Notification_Config__c.")

    # 3. JA_Request_Notification__c Object
    notif_key = "ja_request_notification__c"
    if notif_key not in objects:
        issues.append("CustomObject 'JA_Request_Notification__c' is missing.")
    else:
        notif_obj = objects[notif_key]
        if notif_obj.sharing_model != "Private":
            issues.append(f"JA_Request_Notification__c sharingModel must be 'Private', got '{notif_obj.sharing_model}'.")
        if notif_obj.name_field_type != "AutoNumber":
            issues.append(f"JA_Request_Notification__c Name must be AutoNumber, got '{notif_obj.name_field_type}'.")

        expected_notif_fields = {
            "alert_key__c": ("Text", True, True, True),
            "source_event_key__c": ("Text", False, False, False),
            "event_kind__c": ("Picklist", False, False, False),
            "generation_request__c": ("Lookup", False, False, False),
            "recipient_user__c": ("Lookup", False, False, False),
            "channel__c": ("Picklist", False, False, False),
            "status__c": ("Picklist", False, False, False),
            "payload_fingerprint__c": ("Text", False, False, False),
            "source_revision__c": ("Number", False, False, False),
            "artifact_set_id__c": ("Text", False, False, False),
            "artifact_set_version__c": ("Number", False, False, False),
            "failure_episode_id__c": ("Text", False, False, False),
            "action_code__c": ("Text", False, False, False),
            "attempts__c": ("Number", False, False, False),
            "max_attempts__c": ("Number", False, False, False),
            "next_retry_at__c": ("DateTime", False, False, False),
            "attempt_identifier__c": ("Text", False, False, False),
            "dispatched_at__c": ("DateTime", False, False, False),
            "accepted_at__c": ("DateTime", False, False, False),
            "safe_error_code__c": ("Text", False, False, False),
            "uncertainty_reason__c": ("Text", False, False, False),
            "target_record_id__c": ("Text", False, False, False),
            "notification_title__c": ("Text", False, False, False),
            "notification_body__c": ("Text", False, False, False),
        }
        for fname, (ftype, ext_id, uniq, cs) in expected_notif_fields.items():
            if fname not in notif_obj.fields:
                issues.append(f"Field '{fname}' is missing on JA_Request_Notification__c.")
            else:
                fld = notif_obj.fields[fname]
                if fld.field_type != ftype:
                    issues.append(f"Field '{fname}' on JA_Request_Notification__c must be '{ftype}', got '{fld.field_type}'.")
                if ext_id and not fld.external_id:
                    issues.append(f"Field '{fname}' must be an External ID.")
                if uniq and not fld.unique:
                    issues.append(f"Field '{fname}' must be Unique.")
                if cs and not fld.case_sensitive:
                    issues.append(f"Field '{fname}' must be Case Sensitive.")
                if fname in ("generation_request__c", "recipient_user__c") and fld.delete_constraint != "Restrict":
                    issues.append(f"Field '{fname}' deleteConstraint must be 'Restrict', got '{fld.delete_constraint}'.")

        val_rules = notif_obj.validation_rules
        if "immutable_alert_key" not in val_rules:
            issues.append("Validation rule 'Immutable_Alert_Key' is missing on JA_Request_Notification__c.")
        if "accepted_requires_timestamp" not in val_rules:
            issues.append("Validation rule 'Accepted_Requires_Timestamp' is missing on JA_Request_Notification__c.")
        if "uncertain_requires_reason" not in val_rules:
            issues.append("Validation rule 'Uncertain_Requires_Reason' is missing on JA_Request_Notification__c.")

    # 4. Flows
    for flow_name in ("ja_request_notification_observe", "ja_request_notification_dispatch"):
        if flow_name not in flows:
            issues.append(f"Flow '{flow_name}' is missing.")
        else:
            fl = flows[flow_name]
            if fl.process_type != "AutoLaunchedFlow":
                issues.append(f"Flow '{flow_name}' processType must be 'AutoLaunchedFlow', got '{fl.process_type}'.")
            if fl.status != "Draft":
                issues.append(f"Flow '{flow_name}' initial status must be 'Draft' (inactive), got '{fl.status}'.")

    # 5. Custom Permission
    if custom_perms is not None:
        if "ja_administer_notifications" not in custom_perms:
            issues.append("CustomPermission 'JA_Administer_Notifications' is missing.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_sf08_admin_permission_set(
    perm_set: PermissionSetMetadata,
) -> MetadataCompatibilityReport:
    """Validate that Job_Notification_Administrator PermissionSet grants required admin/recovery authority."""
    issues: list[str] = []
    warnings: list[str] = []

    # Custom permission
    if "ja_administer_notifications" not in perm_set.custom_permissions or not perm_set.custom_permissions["ja_administer_notifications"]:
        issues.append("Permission set must grant enabled customPermission for 'JA_Administer_Notifications'.")

    # Apex class accesses
    for cls_name in ("ja_requestnotificationadmission", "ja_requestnotificationdispatcher", "ja_requestnotificationrecovery"):
        if cls_name not in perm_set.class_accesses or not perm_set.class_accesses[cls_name]:
            issues.append(f"Permission set must grant enabled classAccess for '{cls_name}'.")

    # Flow accesses
    for fl_name in ("ja_request_notification_observe", "ja_request_notification_dispatch"):
        if fl_name not in perm_set.flow_accesses or not perm_set.flow_accesses[fl_name]:
            issues.append(f"Permission set must grant enabled flowAccess for '{fl_name}'.")

    # Object permissions: CRUD on JA_Notification_Config__c & JA_Request_Notification__c
    for obj_name in ("ja_notification_config__c", "ja_request_notification__c"):
        if obj_name not in perm_set.object_permissions:
            issues.append(f"Missing objectPermissions for '{obj_name}'.")
        else:
            op = perm_set.object_permissions[obj_name]
            if not op.allow_read or not op.allow_create or not op.allow_edit or not op.allow_delete:
                issues.append(f"Must grant full CRUD on '{obj_name}'.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_sf09_metadata(
    objects: dict[str, CustomObjectMetadata],
    flows: dict[str, FlowMetadata],
    notif_types: dict[str, CustomNotificationTypeMetadata],
) -> MetadataCompatibilityReport:
    """Validate SF-09 run summary custom object, fields, validation rules, flows, and notification types."""
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Custom Notification Type
    if "ja_run_completed" not in notif_types:
        issues.append("CustomNotificationType 'ja_run_completed' is missing.")
    else:
        nt = notif_types["ja_run_completed"]
        if not nt.desktop:
            issues.append("CustomNotificationType 'ja_run_completed' must have desktop=true.")
        if nt.mobile:
            issues.append("CustomNotificationType 'ja_run_completed' mobile must default to false.")

    # 2. Run_Summary__c Custom Object
    obj_key = "run_summary__c"
    if obj_key not in objects:
        issues.append("CustomObject 'Run_Summary__c' is missing.")
    else:
        obj = objects[obj_key]
        if obj.sharing_model != "Private":
            issues.append(f"Run_Summary__c sharingModel must be 'Private', got '{obj.sharing_model}'.")
        if obj.name_field_type != "Text":
            issues.append(f"Run_Summary__c Name field type must be 'Text', got '{obj.name_field_type}'.")

        expected_fields = {
            "run_id__c": ("Text", True, True, False, True),
            "contract_schema_version__c": ("Text", False, False, False, False),
            "mapping_version__c": ("Text", False, False, False, False),
            "start_time__c": ("DateTime", False, False, False, False),
            "end_time__c": ("DateTime", False, False, False, False),
            "duration_seconds__c": ("Number", False, False, False, False),
            "pipeline_status__c": ("Picklist", False, False, False, False),
            "headline__c": ("Text", False, False, False, False),
            "summary_text__c": ("LongTextArea", False, False, False, False),
            "source_postings_count__c": ("Number", False, False, False, False),
            "canonical_jobs_new__c": ("Number", False, False, False, False),
            "canonical_jobs_updated__c": ("Number", False, False, False, False),
            "canonical_jobs_duplicate__c": ("Number", False, False, False, False),
            "eligible_count__c": ("Number", False, False, False, False),
            "review_count__c": ("Number", False, False, False, False),
            "rejected_count__c": ("Number", False, False, False, False),
            "sync_succeeded__c": ("Number", False, False, False, False),
            "sync_failed__c": ("Number", False, False, False, False),
            "quarantined_count__c": ("Number", False, False, False, False),
            "sources_attempted__c": ("LongTextArea", False, False, False, False),
            "sources_succeeded__c": ("LongTextArea", False, False, False, False),
            "sources_failed__c": ("LongTextArea", False, False, False, False),
            "source_counts__c": ("LongTextArea", False, False, False, False),
            "stage_counts__c": ("LongTextArea", False, False, False, False),
            "coverage_status__c": ("Picklist", False, False, False, False),
            "projection_truncated__c": ("Checkbox", False, False, False, False),
            "error_summary__c": ("LongTextArea", False, False, False, False),
            "pending_work_summary__c": ("LongTextArea", False, False, False, False),
            "revision__c": ("Number", False, False, False, False),
            "payload_hash__c": ("Text", False, False, False, False),
            "first_completion_key__c": ("Text", True, True, False, True),
            "first_payload_hash__c": ("Text", False, False, False, False),
            "first_completed_at__c": ("DateTime", False, False, False, False),
            "first_status__c": ("Picklist", False, False, False, False),
            "first_headline__c": ("Text", False, False, False, False),
            "first_summary_text__c": ("LongTextArea", False, False, False, False),
            "completion_recorded_at__c": ("DateTime", False, False, False, False),
            "notification_recipient__c": ("Lookup", False, False, False, False),
            "notification_status__c": ("Picklist", False, False, False, False),
            "notification_claim_id__c": ("Text", False, False, False, False),
            "notification_attempt_count__c": ("Number", False, False, False, False),
            "notification_last_attempt_at__c": ("DateTime", False, False, False, False),
            "notification_next_attempt_at__c": ("DateTime", False, False, False, False),
            "notification_receipt_id__c": ("Text", False, False, False, False),
            "notification_accepted_at__c": ("DateTime", False, False, False, False),
            "notification_error_code__c": ("Text", False, False, False, False),
            "is_first_completion__c": ("Checkbox", False, False, False, False),
        }

        for fname, (ftype, ext_id, uniq, cs, req) in expected_fields.items():
            if fname not in obj.fields:
                issues.append(f"Field '{fname}' is missing on Run_Summary__c.")
            else:
                fld = obj.fields[fname]
                if fld.field_type != ftype:
                    issues.append(f"Field '{fname}' on Run_Summary__c must be '{ftype}', got '{fld.field_type}'.")
                if ext_id and not fld.external_id:
                    issues.append(f"Field '{fname}' must be an External ID.")
                if uniq and not fld.unique:
                    issues.append(f"Field '{fname}' must be Unique.")
                if req and not fld.required:
                    issues.append(f"Field '{fname}' must be Required.")

        val_rules = obj.validation_rules
        expected_rules = (
            "immutable_run_id",
            "immutable_completion_key",
            "valid_duration",
            "end_not_before_start",
            "confirmed_requires_receipt",
            "unknown_requires_code",
        )
        for rname in expected_rules:
            if rname not in val_rules:
                issues.append(f"Validation rule '{rname}' is missing on Run_Summary__c.")

    # 3. Flow
    flow_key = "ja_run_summary_completion"
    if flow_key not in flows:
        issues.append(f"Flow '{flow_key}' is missing.")
    else:
        fl = flows[flow_key]
        if fl.process_type != "AutoLaunchedFlow":
            issues.append(f"Flow '{flow_key}' processType must be 'AutoLaunchedFlow', got '{fl.process_type}'.")
        if fl.status != "Draft":
            issues.append(f"Flow '{flow_key}' initial status must be 'Draft' (inactive), got '{fl.status}'.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_sf09_worker_permission_set(
    perm_set: PermissionSetMetadata,
) -> MetadataCompatibilityReport:
    """Validate that Job_Summary_Worker permission set enforces scoped integration worker authority."""
    issues: list[str] = []
    warnings: list[str] = []

    obj_key = "run_summary__c"
    if obj_key not in perm_set.object_permissions:
        issues.append(f"Missing objectPermissions for '{obj_key}'.")
    else:
        op = perm_set.object_permissions[obj_key]
        if not op.allow_read or not op.allow_create or not op.allow_edit:
            issues.append(f"Must grant Read/Create/Edit on '{obj_key}'.")
        if op.allow_delete:
            issues.append(f"Must NOT grant Delete on '{obj_key}'.")
        if op.modify_all_records or op.view_all_records:
            issues.append(f"Must NOT grant Modify All / View All on '{obj_key}'.")

    server_managed = {
        "run_summary__c.completion_recorded_at__c",
        "run_summary__c.first_completed_at__c",
        "run_summary__c.first_status__c",
        "run_summary__c.first_headline__c",
        "run_summary__c.first_summary_text__c",
        "run_summary__c.notification_recipient__c",
        "run_summary__c.notification_status__c",
        "run_summary__c.notification_claim_id__c",
        "run_summary__c.notification_attempt_count__c",
        "run_summary__c.notification_last_attempt_at__c",
        "run_summary__c.notification_next_attempt_at__c",
        "run_summary__c.notification_receipt_id__c",
        "run_summary__c.notification_accepted_at__c",
        "run_summary__c.notification_error_code__c",
    }

    for fld in server_managed:
        if fld in perm_set.field_permissions:
            fp = perm_set.field_permissions[fld]
            if fp.editable:
                issues.append(f"Field '{fld}' must be read-only for Job_Summary_Worker, got editable=true.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_sf09_reader_permission_set(
    perm_set: PermissionSetMetadata,
) -> MetadataCompatibilityReport:
    """Validate that Job_Summary_Reader permission set enforces read-only candidate access."""
    issues: list[str] = []
    warnings: list[str] = []

    obj_key = "run_summary__c"
    if obj_key not in perm_set.object_permissions:
        issues.append(f"Missing objectPermissions for '{obj_key}'.")
    else:
        op = perm_set.object_permissions[obj_key]
        if not op.allow_read:
            issues.append(f"Must grant Read on '{obj_key}'.")
        if op.allow_create or op.allow_edit or op.allow_delete:
            issues.append(f"Must NOT grant Create/Edit/Delete on '{obj_key}'.")

    for fld, fp in perm_set.field_permissions.items():
        if fld.startswith("run_summary__c.") and fp.editable:
            issues.append(f"Field '{fld}' must be read-only for Job_Summary_Reader.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def validate_sf09_admin_permission_set(
    perm_set: PermissionSetMetadata,
) -> MetadataCompatibilityReport:
    """Validate that Job_Summary_Administrator permission set grants recovery authority."""
    issues: list[str] = []
    warnings: list[str] = []

    obj_key = "run_summary__c"
    if obj_key not in perm_set.object_permissions:
        issues.append(f"Missing objectPermissions for '{obj_key}'.")
    else:
        op = perm_set.object_permissions[obj_key]
        if not op.allow_read or not op.allow_edit:
            issues.append(f"Must grant Read/Edit on '{obj_key}'.")

    if "ja_runsummaryrecovery" not in perm_set.class_accesses or not perm_set.class_accesses["ja_runsummaryrecovery"]:
        issues.append("Must grant classAccess for 'JA_RunSummaryRecovery'.")

    return MetadataCompatibilityReport(
        compatible=len(issues) == 0,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )

