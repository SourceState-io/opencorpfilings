"""France OAM: an issuer's records filed without its LEI are found through its share ISIN.

On 2026-10-09 SEB's universal registration documents carried no LEI and AXA's
carried a second AXA LEI; both carried the share ISIN. LEI-only lookup found
no annual report for either.
"""

import pytest

from opencorpfilings import Company, ProviderError
from opencorpfilings.providers.france_oam import FranceOAMProvider

LEI = "969500WP61NBK098AC47"
ISIN = "FR0000121709"


def _row(uin, *, lei, isin, code, day, title):
    return {"uin_idt_uin": uin, "uin_dat_amf": f"{day}T09:00:00+00:00",
            "identificationdiffuseur_idi_cod_dif": "370", "identificationsociete_iso_cd_lei": lei,
            "identificationsociete_iso_nom_soc": "SEB S.A.", "identificationsociete_iso_cd_isi": isin,
            "informationdeposee_inf_stp_pri": code, "informationdeposee_inf_stp_inf": f'["{code}", "003000"]'
            if code == "300005" else f'["{code}"]', "informationdeposee_inf_tit_inf": title,
            "informationdeposee_inf_upg_inf_inf_upg_sts": "NEW", "informationdeposee_inf_lng_inf": "Français",
            "url_de_recuperation": f"https://fr.ftp.opendatasoft.com/datadila/INFOFI/370/{uin}.pdf"}


class Transport:
    def __init__(self, extra=()):
        self.wheres = []
        self.own = _row("1_20260730", lei=LEI, isin=ISIN, code="004000", day="2026-07-30",
                        title="Rapport financier semestriel")
        self.unlinked = _row("2_20260326", lei=None, isin=ISIN, code="300005", day="2026-03-26",
                             title="SEB Document d'enregistrement universel 2025")
        self.extra = list(extra)

    def get_json(self, url, *, params):
        where = params["where"]
        self.wheres.append(where)
        if params.get("limit") == 1 and "identificationsociete_iso_cd_isi" not in where:
            rows = [self.own]
        else:
            rows = [self.own, self.unlinked, *self.extra]
            if "003000" in where:
                rows = [row for row in rows if "003000" in row["informationdeposee_inf_stp_inf"]]
        page = rows[params.get("offset", 0): params.get("offset", 0) + params["limit"]]
        return {"total_count": len(rows), "results": page}


def test_annual_report_without_the_lei_is_found_by_the_issuers_isin():
    transport = Transport()
    company = Company(LEI, market="FR", provider=FranceOAMProvider(transport=transport))
    filing = company.filings(form="annual").latest()
    assert filing.filing_id == "370:2_20260326"
    assert filing.entity_id == LEI
    assert filing.provider_metadata["matched_by"] == "isin"
    assert any(f"identificationsociete_iso_cd_isi IN ('{ISIN}')" in where for where in transport.wheres)


def test_a_row_matching_neither_lei_nor_isin_is_still_refused():
    stranger = _row("3_20260401", lei="529900AAAAAAAAAAAAAA", isin="FR0000000000", code="300005",
                    day="2026-04-01", title="Another issuer")
    company = Company(LEI, market="FR", provider=FranceOAMProvider(transport=Transport([stranger])))
    with pytest.raises(ProviderError, match="another issuer"):
        list(company.filings(form="annual"))


def test_french_language_is_an_iso_code_and_the_source_label_is_kept():
    company = Company(LEI, market="FR", provider=FranceOAMProvider(transport=Transport()))
    filing = company.filings(form="interim").latest()
    assert filing.language == "fr"
    assert filing.provider_metadata["informationdeposee_inf_lng_inf"] == "Français"


def test_a_native_code_matches_a_record_that_carries_it_as_a_secondary_code():
    # Legrand files its annual report as a registration document: primary code
    # 300005 with 003000 secondary. form="003000" found it, then raised
    # "returned a filing outside the requested form".
    provider = FranceOAMProvider(transport=Transport())
    urd = provider._filing(_row("3_20260408", lei=LEI, isin=ISIN, code="300005", day="2026-04-08",
                                title="Document d'enregistrement universel"), LEI)
    assert urd.filing_type_raw == "300005"
    assert provider.filing_matches_form(urd, "003000")
    assert provider.filing_matches_form(urd, "300005")
    assert provider.filing_matches_form(urd, "annual")
    assert not provider.filing_matches_form(urd, "004000")


def test_a_searched_candidate_is_resolved_so_listing_also_matches_the_isin():
    # A search row carries only the LEI; the ISIN comes from resolve_entity.
    class SearchTransport(Transport):
        def get_json(self, url, *, params):
            if "group_by" in params:
                return {"total_count": 1, "results": [{
                    "identificationsociete_iso_cd_lei": LEI,
                    "identificationsociete_iso_nom_soc": "SEB S.A.", "latest": "2026-07-30"}]}
            return super().get_json(url, params=params)

    from opencorpfilings import search_companies

    provider = FranceOAMProvider(transport=SearchTransport())
    candidate = search_companies("SEB", market="FR", provider=provider)[0]
    assert candidate.requires_resolution
    filing = Company(candidate, provider=provider).filings(form="annual").latest()
    assert filing.filing_id == "370:2_20260326"
    assert filing.provider_metadata["matched_by"] == "isin"
