#Useful build commands for bgexplorer package

ifeq "$VERBOSE" "0"
VERBOSE=
endif
ifdef VERBOSE
VERBOSE="-v"
endif

all:	doc test

init:
#should we ensure virtenv is setup first?
	pip install -r requirements.txt

test:	
	@echo "Running test suite..."
	python -m unittest $(VERBOSE)

doc:
	@echo "Generating documentation..."
	cd docs && make html

.PHONY:	init test doc

