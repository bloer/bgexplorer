#Useful build commands for bgexplorer package

all:	doc test

init:
#should we ensure virtenv is setup first?
	pip install -r requirements.txt

test:	
	@echo "Running test suite..."
	python -m unittest -v

clean: clean-build clean-pyc clean-docs

clean-build:
	rm -fr .coverage
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	rm -fr .cache/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

clean-pyc:
	find . -name '*.c' -exec rm -f {} +
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyx' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-docs:
	rm -fr docs/_static
	rm -fr docs/_build

doc:
	@echo "Generating documentation..."
	mkdir -p docs/_static
	cd docs && make html

.PHONY:	init test doc clean clean-build clean-pyc clean-docs

