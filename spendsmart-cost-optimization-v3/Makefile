run-api:
	uvicorn app.main:app --reload

run-ui:
	PYTHONPATH=. streamlit run streamlit_app/Home.py

seed:
	PYTHONPATH=. python scripts/seed_demo.py

test-source:
	PYTHONPATH=. python scripts/test_spendsmart_ec2.py

test:
	pytest -q
