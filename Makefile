
build:
	pipenv install --dev

run:
	pipenv run python3 __init__.py

test:
	pipenv run pytest -v tests/ --html=test-report.html --self-contained-html