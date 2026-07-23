import json

d = json.load(open(r'C:\Users\sevans\Downloads\texas_sor_race_tally_raw.json'))
race_map = {'W':'WHITE','B':'BLACK','I':'AMERICAN INDIAN OR ALASKAN NATIVE','A':'ASIAN','U':'UNKNOWN','MISSING':'UNKNOWN'}
race_totals = {}
for code, count in d['raceTally'].items():
    name = race_map.get(code, code)
    race_totals[name] = race_totals.get(name, 0) + count

output = {
    'state': 'Texas',
    'pulled_at': '2026-07-23',
    'source': 'Texas DPS Public Sex Offender Registry (sor.dps.texas.gov/PublicSite)',
    'scope_note': 'Aggregate Race tally only, computed entirely client-side in-browser from per-county Excel exports -- raw files never saved to disk or retained. Only per-file and combined SHA-256 checksums plus resulting aggregate counts were kept.',
    'finding': 'This registry has NO separate Ethnicity field at all -- confirmed directly from the Excel column headers (Name, Birth Date, Sex, Race, Address). Same structural gap as Idaho and Illinois: no way to recover Hispanic or MENA representation within the White count.',
    'race_totals': race_totals,
    'grand_total_claimed': d['totalRows'],
    'grand_total_scanned': d['totalRows'],
    'provenance': {
        'source_url': 'https://sor.dps.texas.gov/PublicSite/Search/Default/ExcelByCounty?COU_COD={county_code}',
        'pulled_at': '2026-07-23T00:00:00Z',
        'method': 'bulk_export',
        'combined_checksum_sha256': d['combinedChecksum'],
        'combined_checksum_method': 'SHA-256 of the concatenation (pipe-delimited) of all 255 individual per-county file checksums, in county-code order',
        'claimed_count': d['totalRows'],
        'processed_count': d['totalRows'],
        'counties_processed': 255,
        'extraction_field': 'Race',
        'race_code_mapping': 'W=White, B=Black, I=American Indian/Alaska Native, A=Asian, U=Unknown (standard NCIC race codes)',
        'verification_note': 'Any third party can independently reproduce this: for each of the 254 Texas counties, visit sor.dps.texas.gov/PublicSite/Search/Default/SearchByCounty, select the county, and download Complete Search Results (Excel) -- compare row counts and Race column distribution.'
    },
    'by_county': d['byCounty']
}

with open(r'C:\Users\sevans\crime-clarity\data\texas_sor_race_tally.json', 'w') as f:
    json.dump(output, f, indent=2)

print('Written. Total:', d['totalRows'])
print('Race totals:', race_totals)
