from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from leadgen.config import get_settings
from leadgen.db import connect, get_lead, init_db, insert_lead
from leadgen.logging_config import setup_logging


def _conn():
    s = get_settings()
    conn = connect(s.db_path)
    init_db(conn)
    return conn


def _auto_export_leads(conn, target: Path | str | None = None) -> None:
    """Automatically export all leads to CSV."""
    from leadgen.reporting import export_table_to_csv

    s = get_settings()
    out = Path(target) if target else s.leads_csv_path
    cnt = export_table_to_csv(conn, "leads", out)
    print(f"Auto-exported {cnt} total leads to {out}")


def cmd_init_db(a):
    _conn()
    print("database ready")


def cmd_find_leads(a):
    conn = _conn()
    if a.source == "places":
        from leadgen.leads import places

        found = places.search(f"{a.query} in {a.city}", limit=a.limit)
        print(f"{len(found)} places found, {places.save(conn, found, category=a.query)} new candidates saved")
    elif a.source == "geoapify":
        from leadgen.leads import geoapify

        found = geoapify.search(a.query, a.city, limit=a.limit)
        print(f"{len(found)} places found, {geoapify.save(conn, found, category=a.query)} new candidates saved")
    else:
        from leadgen.leads import osm

        found = osm.search(a.query, a.city)
        print(f"{len(found)} elements found, {osm.save(conn, found, a.query)} new candidates saved")
    _auto_export_leads(conn, getattr(a, "export_csv", None))


def cmd_verify(a):
    from leadgen.leads.verify import scrub_all, verify_all

    conn = _conn()
    print("verify:", verify_all(conn, a.limit))
    print("scrub:", scrub_all(conn))
    _auto_export_leads(conn)


def cmd_add_lead(a):
    """Insert a lead by hand."""
    from leadgen.leads.verify import timezone_for
    from leadgen.phone import to_e164

    conn = _conn()
    phone = to_e164(a.phone)
    if not phone:
        sys.exit("invalid phone number")
    lid = insert_lead(
        conn,
        source="manual",
        source_id=phone,
        name=a.name,
        category=a.category,
        phone_e164=phone,
        city=a.city,
        state=a.state,
        lat=a.lat,
        lng=a.lng,
        timezone=timezone_for(a.lat, a.lng),
        status="ready",
        address=a.address,
        website_checked=0,
    )
    print(f"lead id {lid}" if lid else "lead already exists")
    _auto_export_leads(conn)


def cmd_import_csv(a):
    from leadgen.leads.csv_import import import_csv

    conn = _conn()
    print(
        import_csv(
            conn,
            a.file,
            default_lat=a.lat,
            default_lng=a.lng,
            default_city=a.city,
            default_state=a.state,
            source=a.source_label,
        )
    )
    _auto_export_leads(conn)


def cmd_dnc_add(a):
    from leadgen.compliance.gates import add_dnc
    from leadgen.phone import to_e164

    phone = to_e164(a.phone)
    if not phone:
        sys.exit("invalid phone number")
    add_dnc(_conn(), phone, a.reason)
    print(f"{phone} added to DNC")


def cmd_export_csv(a):
    from leadgen.reporting import export_table_to_csv

    conn = _conn()
    cnt = export_table_to_csv(conn, a.table, a.output)
    print(f"Exported {cnt} rows from '{a.table}' to {a.output}")


def cmd_stats(a):
    from leadgen.reporting import get_lead_stats

    conn = _conn()
    stats = get_lead_stats(conn)
    total = sum(stats.values())
    print("Leads Breakdown by Status:")
    if stats:
        for status, cnt in sorted(stats.items()):
            print(f"  - {status:<15}: {cnt:>5}")
    else:
        print("  (no leads in database)")
    print(f"Total Leads: {total}")


def cmd_enrich(a):
    from leadgen.enrichment import enrich_lead

    s = get_settings()
    conn = _conn()
    lead = get_lead(conn, a.lead_id)
    if lead is None:
        sys.exit(f"error: lead #{a.lead_id} not found")
    if lead["status"] != "ready":
        sys.exit(f"error: lead #{a.lead_id} is '{lead['status']}', not 'ready'. Only ready leads can be enriched.")

    enrichment = enrich_lead(conn, a.lead_id, settings=s)

    print(f"Enriched Lead #{a.lead_id}: {lead['name']}")
    if enrichment.place_id:
        print(f"  Place ID: {enrichment.place_id}")
    print(f"  Rating: {enrichment.rating or 'N/A'} ({enrichment.review_count or 0} reviews)")
    print(f"  Top review snippets: {len(enrichment.top_reviews)}")
    print(f"  Categories: {', '.join(enrichment.categories) if enrichment.categories else 'None'}")
    print(f"  Photo references: {len(enrichment.photo_refs)}")
    print(f"  Website absent: {'Yes' if enrichment.website_confirmed_none else 'No'}")
    if enrichment.owner_notes:
        print(f"  Notes: {enrichment.owner_notes.strip()}")
    print(f"  Data richness score: {enrichment.data_richness:.2f}")


def cmd_purge_enrichment(a):
    from leadgen.db import purge_expired_enrichment

    conn = _conn()
    purged = purge_expired_enrichment(conn)
    print(f"Purged expiring fields from {purged} expired enrichment record(s)")


def cmd_export_facts(a):
    from leadgen.facts import export_all_ready_facts, export_facts_for_lead

    if not a.lead_id and not a.all_ready:
        sys.exit("error: specify --lead-id <N> or --all-ready")

    conn = _conn()
    out_dir = Path(a.output_dir) if a.output_dir else Path("packets")

    if a.lead_id:
        try:
            path = export_facts_for_lead(conn, a.lead_id, base_dir=out_dir)
            print(f"Exported facts for lead #{a.lead_id} to {path}")
        except ValueError as e:
            sys.exit(f"error: {e}")
    elif a.all_ready:
        paths = export_all_ready_facts(conn, base_dir=out_dir)
        print(f"Exported facts for {len(paths)} ready lead(s) to {out_dir}")


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    p = argparse.ArgumentParser(prog="leadgen", description="Local business lead generation and facts export")
    sub = p.add_subparsers(dest="cmd", required=True)

    # init-db
    sub.add_parser("init-db", help="Create tables if they don't exist")

    # find-leads
    p_find = sub.add_parser("find-leads", help="Search OSM, Places, or Geoapify for candidate businesses")
    p_find.add_argument("query", help="Category or keyword (e.g. plumber, restaurant)")
    p_find.add_argument("city", help="City name or bounding area")
    p_find.add_argument("--source", choices=["osm", "places", "geoapify"], default="osm")
    p_find.add_argument("--limit", type=int, default=40)
    p_find.add_argument("--export-csv", default=None, help="Export path for leads CSV")
    p_find.set_defaults(func=cmd_find_leads)

    # verify
    p_ver = sub.add_parser("verify", help="Check website presence and scrub against DNC")
    p_ver.add_argument("--limit", type=int, default=500)
    p_ver.set_defaults(func=cmd_verify)

    # add-lead
    p_add = sub.add_parser("add-lead", help="Manually insert a ready lead")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--phone", required=True)
    p_add.add_argument("--city", required=True)
    p_add.add_argument("--state", required=True)
    p_add.add_argument("--lat", type=float, default=None)
    p_add.add_argument("--lng", type=float, default=None)
    p_add.add_argument("--address", default=None)
    p_add.add_argument("--category", default=None)
    p_add.set_defaults(func=cmd_add_lead)

    # import-csv
    p_imp = sub.add_parser("import-csv", help="Import leads from a CSV file")
    p_imp.add_argument("--file", required=True)
    p_imp.add_argument("--lat", type=float, default=None)
    p_imp.add_argument("--lng", type=float, default=None)
    p_imp.add_argument("--city", default=None)
    p_imp.add_argument("--state", default=None)
    p_imp.add_argument("--source-label", default="csv")
    p_imp.set_defaults(func=cmd_import_csv)

    # dnc-add
    p_dnc = sub.add_parser("dnc-add", help="Add a phone number to internal DNC list")
    p_dnc.add_argument("phone")
    p_dnc.add_argument("--reason", default="opt-out")
    p_dnc.set_defaults(func=cmd_dnc_add)

    # export-csv
    p_exp = sub.add_parser("export-csv", help="Export a table to CSV")
    p_exp.add_argument("--table", choices=["leads", "dnc", "lead_enrichment"], default="leads")
    p_exp.add_argument("--output", default="leads.csv")
    p_exp.set_defaults(func=cmd_export_csv)

    # stats
    p_stats = sub.add_parser("stats", help="Show lead counts by status")
    p_stats.set_defaults(func=cmd_stats)

    # enrich
    p_enr = sub.add_parser("enrich", help="Fetch Google Places details and calculate data richness")
    p_enr.add_argument("lead_id", type=int)
    p_enr.set_defaults(func=cmd_enrich)

    # purge-enrichment
    p_purge = sub.add_parser("purge-enrichment", help="Purge expiring fields from expired enrichment rows")
    p_purge.set_defaults(func=cmd_purge_enrichment)

    # export-facts
    p_facts = sub.add_parser("export-facts", help="Export factual JSON packet for ready leads")
    p_facts.add_argument("--lead-id", type=int, default=None, help="Export facts for a single ready lead")
    p_facts.add_argument("--all-ready", action="store_true", help="Export facts for all ready leads")
    p_facts.add_argument("--output-dir", default="packets", help="Destination directory for packets")
    p_facts.set_defaults(func=cmd_export_facts)

    sub.choices["init-db"].set_defaults(func=cmd_init_db)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
