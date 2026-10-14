"""Occurrence-preserving facts from original XBRL and inline XBRL files."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from .errors import ParseError
from .models import MAX_ARCHIVE_MEMBER_BYTES, MAX_STREAMED_MEMBER_BYTES, FilingFact, Provenance


_XBRLI = "http://www.xbrl.org/2003/instance"
_XBRLDI = "http://xbrl.org/2006/xbrldi"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_INLINE = {"http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL"}
_INLINE_EXCLUDES = {f"{{{namespace}}}exclude" for namespace in _INLINE}
_INLINE_CONTINUATIONS = {f"{{{namespace}}}continuation" for namespace in _INLINE}
_INLINE_FACTS = {f"{{{namespace}}}{kind}" for namespace in _INLINE
                 for kind in ("nonFraction", "nonNumeric", "fraction")}
MAX_XBRL_INSTANCE_BYTES = 50_000_000


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError as exc:
        raise ParseError(f"invalid XBRL context date {value!r}") from exc


def _qname(tag: str, prefixes: dict[str, str]) -> str:
    if not tag.startswith("{"):
        return tag
    namespace, local = tag[1:].split("}", 1)
    prefix = prefixes.get(namespace)
    return f"{prefix}:{local}" if prefix else f"{{{namespace}}}{local}"


def _unit_text(unit: ET.Element) -> str:
    """Represent the source unit's product or explicit numerator/denominator."""
    measure = f"{{{_XBRLI}}}measure"
    divide = unit.find(f"{{{_XBRLI}}}divide")
    if divide is None:
        values = [(item.text or "").strip() for item in unit.findall(measure)]
        if not values or not all(values):
            raise ParseError(f"invalid XBRL unit {unit.get('id')!r}")
        return " * ".join(values)
    numerator = divide.find(f"{{{_XBRLI}}}unitNumerator")
    denominator = divide.find(f"{{{_XBRLI}}}unitDenominator")
    if numerator is None or denominator is None:
        raise ParseError(f"invalid XBRL unit {unit.get('id')!r}")
    top = [(item.text or "").strip() for item in numerator.findall(measure)]
    bottom = [(item.text or "").strip() for item in denominator.findall(measure)]
    if not top or not bottom or not all(top + bottom):
        raise ParseError(f"invalid XBRL unit {unit.get('id')!r}")
    top_text, bottom_text = " * ".join(top), " * ".join(bottom)
    if len(top) > 1:
        top_text = f"({top_text})"
    if len(bottom) > 1:
        bottom_text = f"({bottom_text})"
    return f"{top_text} / {bottom_text}"


def _context(element: ET.Element) -> tuple[date | None, date | None, dict[str, str]]:
    """A context's period (start, end; an instant has only an end) and its dimension members."""
    period = element.find(f"{{{_XBRLI}}}period")
    start = end = None
    if period is not None:
        instant = period.findtext(f"{{{_XBRLI}}}instant")
        if instant:
            end = _date(instant)
        else:
            start = _date(period.findtext(f"{{{_XBRLI}}}startDate"))
            end = _date(period.findtext(f"{{{_XBRLI}}}endDate"))
    dimensions: dict[str, str] = {}
    for member in element.iter():
        if member.tag in {f"{{{_XBRLDI}}}explicitMember", f"{{{_XBRLDI}}}typedMember"}:
            dimension = member.get("dimension")
            if dimension:
                dimensions[dimension] = "".join(member.itertext()).strip()
    return start, end, dimensions


def parse_xbrl_instance(
    content: bytes | Path,
    *,
    document_url: str,
    entry_path: str,
    provider: str,
    regulator: str,
    jurisdiction: str,
    filing_id: str,
) -> list[FilingFact]:
    """Read raw item occurrences; leave all accounting interpretation upstream."""
    size = content.stat().st_size if isinstance(content, Path) else len(content)
    if size > MAX_XBRL_INSTANCE_BYTES:
        raise ParseError(f"XBRL instance {entry_path} exceeds the 50 MB parser limit")
    prefixes: dict[str, str] = {}

    def children():
        """Yield completed root children, then release each parsed subtree."""
        source = str(content) if isinstance(content, Path) else BytesIO(content)
        depth = 0
        root = None
        ordinal = 0
        try:
            for event, item in ET.iterparse(source, events=("start-ns", "start", "end")):
                if event == "start-ns":
                    prefix, namespace = item
                    if prefix and namespace not in prefixes:
                        prefixes[namespace] = prefix
                elif event == "start":
                    depth += 1
                    if depth == 1:
                        root = item
                        if root.tag != f"{{{_XBRLI}}}xbrl":
                            raise ParseError(f"{entry_path} is not an XBRL instance")
                else:
                    if depth == 2:
                        yield ordinal, item
                        ordinal += 1
                        root.clear()
                    depth -= 1
        except ET.ParseError as exc:
            raise ParseError(f"invalid XBRL instance XML in {entry_path}") from exc

    contexts: dict[str, tuple[date | None, date | None, dict[str, str], dict[str, str]]] = {}
    units: dict[str, str] = {}
    for _, child in children():
        if child.tag == f"{{{_XBRLI}}}context":
            context_id = child.get("id")
            if not context_id:
                continue
            if context_id in contexts:
                raise ParseError(f"duplicate XBRL context id {context_id!r} in {entry_path}")
            start, end, dimensions = _context(child)
            identifier = child.find(f".//{{{_XBRLI}}}identifier")
            identity = {"identifier_scheme": identifier.get("scheme", ""), "identifier": identifier.text or ""} if identifier is not None else {}
            contexts[context_id] = (start, end, dimensions, identity)
        elif child.tag == f"{{{_XBRLI}}}unit":
            unit_id = child.get("id")
            if unit_id:
                if unit_id in units:
                    raise ParseError(f"duplicate XBRL unit id {unit_id!r} in {entry_path}")
                units[unit_id] = _unit_text(child)

    facts: list[FilingFact] = []
    for ordinal, child in children():
        context_id = child.get("contextRef")
        if not context_id:
            continue
        if context_id not in contexts:
            raise ParseError(f"XBRL fact has missing context {context_id!r} in {entry_path}")
        start, end, dimensions, identity = contexts[context_id]
        unit_id = child.get("unitRef")
        concept = _qname(child.tag, prefixes)
        raw = {
            "attributes": dict(child.attrib),
            "context": context_id,
            "entity": identity,
            "entry_path": entry_path,
            "ordinal": ordinal,
        }
        facts.append(FilingFact(
            concept_raw=concept,
            value="" if child.get(f"{{{_XSI}}}nil") == "true" else "".join(child.itertext()).strip(),
            unit=units.get(unit_id) if unit_id else None,
            period_start=start,
            period_end=end,
            context_id=context_id,
            dimensions=dimensions.copy(),
            taxonomy=child.tag[1:].split("}", 1)[0] if child.tag.startswith("{") else None,
            source_location=f"{document_url}::{entry_path}#fact-{ordinal}",
            provenance=Provenance(provider, regulator, jurisdiction, document_url, f"{filing_id}:{entry_path}:{ordinal}", raw=raw),
            provider_metadata=raw,
        ))
    return facts


def parse_ixbrl_xhtml(
    content: bytes | Path,
    *,
    document_url: str,
    entry_path: str,
    provider: str,
    regulator: str,
    jurisdiction: str,
    filing_id: str,
) -> list[FilingFact]:
    """Expose inline fact tags and source context without applying transformations.

    ``value`` is the displayed lexical text. The inline ``format``, ``scale``
    and ``sign`` attributes stay in provider_metadata; no numeric conversion
    or accounting mapping is implied.
    """
    def displayed_text(element: ET.Element) -> str:
        parts = [element.text or ""]
        for child in element:
            if child.tag not in _INLINE_EXCLUDES:
                parts.append(displayed_text(child))
            parts.append(child.tail or "")
        return "".join(parts)

    content_size = content.stat().st_size if isinstance(content, Path) else len(content)
    # A file-backed document is parsed incrementally; bytes in memory keep the 100 MB bound.
    limit = MAX_STREAMED_MEMBER_BYTES if isinstance(content, Path) else MAX_ARCHIVE_MEMBER_BYTES
    if content_size > limit:
        raise ParseError(f"iXBRL document {entry_path} exceeds the {limit} byte parser limit")

    namespace_by_prefix: dict[str, str] = {}

    def walk(targets: set[str]):
        """Yield completed target subtrees, discarding unrelated XML as we go."""
        stack: list[ET.Element] = []
        positions: list[int] = []
        protected = 0
        ordinal = -1
        source = str(content) if isinstance(content, Path) else BytesIO(content)
        for event, item in ET.iterparse(source, events=("start-ns", "start", "end")):
            if event == "start-ns":
                prefix, namespace = item
                if prefix and prefix not in namespace_by_prefix:
                    namespace_by_prefix[prefix] = namespace
                continue
            element = item
            if event == "start":
                ordinal += 1
                stack.append(element)
                positions.append(ordinal)
                if element.tag in targets:
                    protected += 1
                continue
            if element.tag in targets:
                yield positions[-1], element
                protected -= 1
            if protected == 0:
                if len(stack) > 1:
                    stack[-2].remove(element)
                element.clear()
            stack.pop()
            positions.pop()

    contexts: dict[str, tuple[date | None, date | None, dict[str, str]]] = {}
    units: dict[str, str] = {}
    continuations: dict[str, tuple[str, str | None]] = {}
    try:
        for _, element in walk({f"{{{_XBRLI}}}context", f"{{{_XBRLI}}}unit", *_INLINE_CONTINUATIONS}):
            if element.tag == f"{{{_XBRLI}}}context":
                context_id = element.get("id")
                if not context_id:
                    continue
                if context_id in contexts:
                    raise ParseError(f"duplicate iXBRL context id {context_id!r} in {entry_path}")
                contexts[context_id] = _context(element)
            elif element.tag == f"{{{_XBRLI}}}unit":
                unit_id = element.get("id")
                if unit_id:
                    if unit_id in units:
                        raise ParseError(f"duplicate iXBRL unit id {unit_id!r} in {entry_path}")
                    units[unit_id] = _unit_text(element)
            elif element.get("id"):
                continuation_id = element.get("id")
                if continuation_id in continuations:
                    raise ParseError(f"duplicate iXBRL continuation id {continuation_id!r} in {entry_path}")
                continuations[continuation_id] = (displayed_text(element), element.get("continuedAt"))

        ordered_facts: list[tuple[int, FilingFact]] = []
        for ordinal, element in walk(_INLINE_FACTS):
            concept = element.get("name")
            context_id = element.get("contextRef")
            if not concept or not context_id or context_id not in contexts:
                raise ParseError(f"inline fact {ordinal} has no valid concept/context in {entry_path}")
            start, end, dimensions = contexts[context_id]
            if _local(element.tag) == "fraction":
                numerator = next((child for child in element if _local(child.tag) == "numerator"), None)
                denominator = next((child for child in element if _local(child.tag) == "denominator"), None)
                if numerator is None or denominator is None:
                    raise ParseError(f"inline fraction {ordinal} has no numerator/denominator in {entry_path}")
                value = f"{displayed_text(numerator).strip()}/{displayed_text(denominator).strip()}"
            else:
                value = displayed_text(element)
            continuation_id = element.get("continuedAt")
            seen: set[str] = set()
            while continuation_id:
                if continuation_id in seen or continuation_id not in continuations:
                    raise ParseError(f"inline fact {ordinal} has an invalid continuation in {entry_path}")
                seen.add(continuation_id)
                extra_text, continuation_id = continuations[continuation_id]
                value += extra_text
            unit_id = element.get("unitRef")
            attributes = dict(element.attrib)
            raw = {"attributes": attributes, "entry_path": entry_path, "ordinal": ordinal,
                   "value_kind": "inline_display_text_untransformed"}
            prefix = concept.split(":", 1)[0] if ":" in concept else ""
            ordered_facts.append((ordinal, FilingFact(
                concept_raw=concept,
                value=value.strip(),
                unit=units.get(unit_id) if unit_id else None,
                period_start=start,
                period_end=end,
                context_id=context_id,
                dimensions=dimensions.copy(),
                taxonomy=namespace_by_prefix.get(prefix),
                source_location=f"{document_url}::{entry_path}#ix-fact-{ordinal}",
                provenance=Provenance(provider, regulator, jurisdiction, document_url,
                                      f"{filing_id}:{entry_path}:{ordinal}", raw=raw),
                provider_metadata=raw,
            )))
    except ET.ParseError as exc:
        raise ParseError(f"invalid iXBRL XHTML in {entry_path}") from exc
    return [fact for _, fact in sorted(ordered_facts, key=lambda item: item[0])]
