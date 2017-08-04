INSTALLATION
============

python virtualenv
-----------------

*bgexplorer* relies on a number of python packages, listed in requirements.txt. The easiest way to handle these dependencies, especially on a shared system, is to use python's *virtualenv* package.  The .gitignore file is configured to expect a virtualenv installation in 'virtenv'. So recommended installation procedure is (assuming virtualenv is already installed on the system):

    |bgexplorer> virtualenv virtenv
    |bgexplorer> source virtenv/bin/activate
    |bgexplorer> pip install -r requirements.txt

The install command may have to be repeated if requirements change. 

