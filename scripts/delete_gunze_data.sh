#!/usr/bin/env bash
set -euo pipefail

if [[ "${CONFIRM_DELETE_GUNZE:-}" != "1" ]]; then
  echo "Refusing to delete data. Re-run with CONFIRM_DELETE_GUNZE=1" >&2
  exit 1
fi

docker compose exec -T db psql -U supplier -d supplier -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;

CREATE TEMP TABLE target_brands ON COMMIT DROP AS
SELECT id
FROM brands
WHERE lower(trim(name)) = '郡士'
   OR normalized_name = '郡士';

CREATE TEMP TABLE target_products ON COMMIT DROP AS
SELECT id FROM products
WHERE brand_id IN (SELECT id FROM target_brands);

CREATE TEMP TABLE target_skus ON COMMIT DROP AS
SELECT id FROM supplier_skus
WHERE brand_id IN (SELECT id FROM target_brands)
   OR product_id IN (SELECT id FROM target_products);

CREATE TEMP TABLE target_offers ON COMMIT DROP AS
SELECT id FROM supplier_offers
WHERE product_id IN (SELECT id FROM target_products)
   OR supplier_sku_id IN (SELECT id FROM target_skus);

DELETE FROM inventory_snapshots
WHERE offer_id IN (SELECT id FROM target_offers);

DELETE FROM supplier_offers
WHERE id IN (SELECT id FROM target_offers);

DELETE FROM supplier_skus
WHERE id IN (SELECT id FROM target_skus);

DELETE FROM products
WHERE id IN (SELECT id FROM target_products);

DELETE FROM supplier_brand_cooperations
WHERE brand_id IN (SELECT id FROM target_brands);

DELETE FROM brands b
WHERE b.id IN (SELECT id FROM target_brands)
  AND NOT EXISTS (SELECT 1 FROM products p WHERE p.brand_id = b.id)
  AND NOT EXISTS (SELECT 1 FROM supplier_skus s WHERE s.brand_id = b.id)
  AND NOT EXISTS (
    SELECT 1 FROM supplier_brand_cooperations c WHERE c.brand_id = b.id
  );

COMMIT;

SELECT
  (SELECT count(*) FROM brands
   WHERE lower(trim(name)) = '郡士' OR normalized_name = '郡士') AS remaining_brands,
  (SELECT count(*) FROM products p JOIN brands b ON b.id = p.brand_id
   WHERE lower(trim(b.name)) = '郡士' OR b.normalized_name = '郡士') AS remaining_products,
  (SELECT count(*) FROM supplier_skus s JOIN brands b ON b.id = s.brand_id
   WHERE lower(trim(b.name)) = '郡士' OR b.normalized_name = '郡士') AS remaining_skus,
  (SELECT count(*) FROM supplier_brand_cooperations c JOIN brands b ON b.id = c.brand_id
   WHERE lower(trim(b.name)) = '郡士' OR b.normalized_name = '郡士') AS remaining_cooperations;
SQL
