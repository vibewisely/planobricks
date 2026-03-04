# Databricks notebook source
# MAGIC %md
# MAGIC # Brand Identification via Vision Model
# MAGIC
# MAGIC **PlanoBricks — Planogram Compliance Platform**
# MAGIC
# MAGIC This notebook uses Databricks Foundation Model API (`ai_query` + Claude Haiku 4.5)
# MAGIC to identify the 10 brand categories in the [Grocery Dataset](https://github.com/gulvarol/grocerydataset)
# MAGIC from cropped brand logo images stored in a Unity Catalog Volume.
# MAGIC
# MAGIC ### Pipeline
# MAGIC 1. Read `BrandImages/<category>/*.jpg` from UC Volume (cropped brand logos)
# MAGIC 2. Sample 3 images per category for triple-validation
# MAGIC 3. Send each image to `databricks-claude-haiku-4-5` via `ai_query(files => ...)`
# MAGIC 4. Verify 3/3 consistency per category
# MAGIC 5. Persist the validated mapping to `planobricks_reference.brand_mapping`
# MAGIC
# MAGIC ### Data Source
# MAGIC - **Paper**: Varol & Kuzu, *"Toward Retail Product Recognition on Grocery Shelves"*, ICIVC 2014
# MAGIC - **Volume**: `/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images/`
# MAGIC - **Model**: `databricks-claude-haiku-4-5` (Anthropic, vision-capable, cost-efficient)

# COMMAND ----------

CATALOG = "serverless_stable_wunnava_catalog"
SCHEMA = "planobricks_reference"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/inputs/images"
VISION_MODEL = "databricks-claude-haiku-4-5"
BRAND_TABLE = f"{CATALOG}.{SCHEMA}.brand_mapping"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Explore the Brand Image Dataset

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Count reference brand images per category
# MAGIC SELECT
# MAGIC   regexp_extract(_metadata.file_path, '.*/BrandImages/(\d+)/.*', 1) AS category_id,
# MAGIC   COUNT(*) AS image_count
# MAGIC FROM read_files(
# MAGIC   '/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images/BrandImages/',
# MAGIC   format => 'binaryFile',
# MAGIC   recursiveFileLookup => true
# MAGIC )
# MAGIC GROUP BY 1
# MAGIC ORDER BY CAST(category_id AS INT)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Vision-Based Brand Identification
# MAGIC
# MAGIC We sample 3 images per category (`*_N1.jpg`, `*_N2.jpg`, `*_N5.jpg`) and ask the
# MAGIC vision model to identify the brand name from each cropped logo image.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Pass 1: Sample *_N1.jpg
# MAGIC SELECT
# MAGIC   regexp_extract(_metadata.file_path, '.*/BrandImages/(\d+)/.*', 1) AS category_id,
# MAGIC   _metadata.file_name AS filename,
# MAGIC   ai_query(
# MAGIC     'databricks-claude-haiku-4-5',
# MAGIC     'This is a cropped brand logo from a retail product on a grocery shelf in Turkey (2014). Identify the brand name. Return ONLY the brand name.',
# MAGIC     files => content
# MAGIC   ) AS brand_name
# MAGIC FROM read_files(
# MAGIC   '/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images/BrandImages/',
# MAGIC   format => 'binaryFile',
# MAGIC   recursiveFileLookup => true,
# MAGIC   pathGlobFilter => '*_N1.jpg'
# MAGIC )
# MAGIC WHERE regexp_extract(_metadata.file_path, '.*/BrandImages/(\d+)/.*', 1) IN ('1','2','3','4','5','6','7','8','9','10')
# MAGIC ORDER BY CAST(category_id AS INT)

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Pass 2: Sample *_N2.jpg
# MAGIC SELECT
# MAGIC   regexp_extract(_metadata.file_path, '.*/BrandImages/(\d+)/.*', 1) AS category_id,
# MAGIC   _metadata.file_name AS filename,
# MAGIC   ai_query(
# MAGIC     'databricks-claude-haiku-4-5',
# MAGIC     'This is a cropped brand logo from a retail product on a grocery shelf in Turkey (2014). Identify the brand name. Return ONLY the brand name.',
# MAGIC     files => content
# MAGIC   ) AS brand_name
# MAGIC FROM read_files(
# MAGIC   '/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images/BrandImages/',
# MAGIC   format => 'binaryFile',
# MAGIC   recursiveFileLookup => true,
# MAGIC   pathGlobFilter => '*_N2.jpg'
# MAGIC )
# MAGIC WHERE regexp_extract(_metadata.file_path, '.*/BrandImages/(\d+)/.*', 1) IN ('1','2','3','4','5','6','7','8','9','10')
# MAGIC ORDER BY CAST(category_id AS INT)

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Pass 3: Sample *_N5.jpg
# MAGIC SELECT
# MAGIC   regexp_extract(_metadata.file_path, '.*/BrandImages/(\d+)/.*', 1) AS category_id,
# MAGIC   _metadata.file_name AS filename,
# MAGIC   ai_query(
# MAGIC     'databricks-claude-haiku-4-5',
# MAGIC     'This is a cropped brand logo from a retail product on a grocery shelf in Turkey (2014). Identify the brand name. Return ONLY the brand name.',
# MAGIC     files => content
# MAGIC   ) AS brand_name
# MAGIC FROM read_files(
# MAGIC   '/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images/BrandImages/',
# MAGIC   format => 'binaryFile',
# MAGIC   recursiveFileLookup => true,
# MAGIC   pathGlobFilter => '*_N5.jpg'
# MAGIC )
# MAGIC WHERE regexp_extract(_metadata.file_path, '.*/BrandImages/(\d+)/.*', 1) IN ('1','2','3','4','5','6','7','8','9','10')
# MAGIC ORDER BY CAST(category_id AS INT)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Persist the Validated Brand Mapping
# MAGIC
# MAGIC All 3 passes returned identical results — 100% consistency. The confirmed mapping:
# MAGIC
# MAGIC | ID | Brand | Count | Notes |
# MAGIC |----|-------|-------|-------|
# MAGIC | 0  | Other (Untracked) | 10,440 | Negative class — products not in the 10 tracked categories |
# MAGIC | 1  | Marlboro | 304 | |
# MAGIC | 2  | Kent | 998 | Most prevalent tracked brand |
# MAGIC | 3  | Camel | 67 | |
# MAGIC | 4  | Parliament | 412 | |
# MAGIC | 5  | Pall Mall | 114 | |
# MAGIC | 6  | Monte Carlo | 190 | |
# MAGIC | 7  | Winston | 311 | |
# MAGIC | 8  | Lucky Strike | 195 | |
# MAGIC | 9  | 2001 | 78 | Turkish tobacco brand |
# MAGIC | 10 | Lark | 75 | |

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE serverless_stable_wunnava_catalog.planobricks_reference.brand_mapping (
# MAGIC   brand_id INT COMMENT 'Brand category ID from the Grocery Dataset (0-10)',
# MAGIC   brand_name STRING COMMENT 'Brand name identified by vision model (Claude Haiku 4.5)',
# MAGIC   product_count INT COMMENT 'Number of annotated product instances across all shelf images',
# MAGIC   identification_method STRING COMMENT 'How the brand was identified',
# MAGIC   confidence STRING COMMENT 'Confidence level of identification'
# MAGIC )
# MAGIC COMMENT 'Brand name mapping for the Grocery Dataset, identified using Databricks Foundation Model API (ai_query + Claude Haiku 4.5 vision) on BrandImages from UC Volume.'
# MAGIC TBLPROPERTIES (
# MAGIC   'source.dataset' = 'gulvarol/grocerydataset',
# MAGIC   'source.paper' = 'Varol & Kuzu, Toward Retail Product Recognition on Grocery Shelves, ICIVC 2014',
# MAGIC   'identified_by' = 'databricks-claude-haiku-4-5 via ai_query',
# MAGIC   'identified_at' = '2026-03-03'
# MAGIC )

# COMMAND ----------

# MAGIC %sql
# MAGIC INSERT INTO serverless_stable_wunnava_catalog.planobricks_reference.brand_mapping VALUES
# MAGIC   (0,  'Other (Untracked)', 10440, 'dataset_definition',        'N/A - negative class per dataset README'),
# MAGIC   (1,  'Marlboro',          304,   'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (2,  'Kent',              998,   'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (3,  'Camel',             67,    'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (4,  'Parliament',        412,   'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (5,  'Pall Mall',         114,   'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (6,  'Monte Carlo',       190,   'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (7,  'Winston',           311,   'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (8,  'Lucky Strike',      195,   'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (9,  '2001',              78,    'vision_model_3x_validated', 'high - 3/3 consistent'),
# MAGIC   (10, 'Lark',              75,    'vision_model_3x_validated', 'high - 3/3 consistent')

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM serverless_stable_wunnava_catalog.planobricks_reference.brand_mapping ORDER BY brand_id

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Verify — Query Brand Mapping Table
# MAGIC
# MAGIC The brand mapping is now persisted in Unity Catalog and can be joined with
# MAGIC annotation data for the Planogram Compliance dashboard.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Distribution of tracked vs untracked products
# MAGIC SELECT
# MAGIC   CASE WHEN brand_id = 0 THEN 'Untracked' ELSE 'Tracked' END AS category,
# MAGIC   SUM(product_count) AS total_products,
# MAGIC   ROUND(SUM(product_count) * 100.0 / (SELECT SUM(product_count) FROM serverless_stable_wunnava_catalog.planobricks_reference.brand_mapping), 1) AS pct
# MAGIC FROM serverless_stable_wunnava_catalog.planobricks_reference.brand_mapping
# MAGIC GROUP BY 1
# MAGIC ORDER BY 1
