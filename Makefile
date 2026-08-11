.PHONY: build validate verify verify-online package-dataset deploy-space deploy-dataset-metadata

build:
	python3 scripts/build_site_data.py

validate:
	python3 scripts/validate_projects.py

verify: build validate
	python3 scripts/verify_deployment.py

verify-online: verify
	python3 scripts/verify_deployment.py --online

package-dataset:
	python3 scripts/package_dataset.py

deploy-space:
	python3 scripts/deploy_hf_space.py

deploy-dataset-metadata:
	python3 scripts/deploy_hf_dataset.py
