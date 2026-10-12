.PHONY: install all data dbt docs report test clean

export DBT_PROFILES_DIR := $(CURDIR)/dbt
export WAREHOUSE_PATH   := $(CURDIR)/data/warehouse.duckdb
export RAW_DIR          := $(CURDIR)/data/raw

install:
	pip install -r requirements.txt

all:            ## generate -> dbt build (models + tests) -> analysis -> report
	python pipeline.py

data:
	python data_gen/generate.py

dbt:
	cd dbt && dbt build

docs:           ## dbt lineage docs at http://localhost:8080
	cd dbt && dbt docs generate && dbt docs serve

report:         ## re-run analysis + report on the existing warehouse
	python pipeline.py --skip-generate

test:
	python -m pytest -q tests

clean:
	rm -rf data/raw data/*.duckdb data/ground_truth.json dbt/target dbt/logs
