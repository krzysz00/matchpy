.PHONY: init dev-install install test doctest check coverage\
api-docs gen-api-docs docs

init:
	pip install -r requirements.txt

dev-install:
	pip install -e .

install:
	pip install .

test:
	py.test tests/ --doctest-modules matchpy/ README.rst docs/example.rst

doctest:
	py.test --doctest-modules -k "not tests" matchpy/ README.rst docs/example.rst

check:
	pylint matchpy

coverage:
	py.test --cov=matchpy --cov-report html --cov-report term tests/

api-docs: | gen-api-docs docs

gen-api-docs:
	rm -rf docs/api
	sphinx-apidoc -e -T -o docs/api matchpy

docs:
	cd docs && $(MAKE) html
