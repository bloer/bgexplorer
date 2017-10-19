#Useful build commands for bgexplorer package

all:	doc test

init:
#should we ensure virtenv is setup first?
	pip install -r requirements.txt

test:	
	@echo "Running test suite..."
	python -m unittest -v

doc:
	@echo "Generating documentation..."
	cd docs && make html

.PHONY:	init test doc

