from setuptools import setup, find_packages

setup(name='bgexplorer',
      version='0.2',
      description='Web app for exploring details of background modeling',
      url='http://github.com/bloer/bgexplorer',
      author='Ben Loer',
      author_email='ben.loer@pnnl.gov',
      license='MIT',
      packages=find_packages(),
      package_data={
          'bgexplorer': ['templates/*.html','static/*','static/*/*'],
          'bgexplorer.modeleditor': ['templates/*.html'],
          'bgexplorer.modelviewer':['templates/*.html','static/*','static/*/*'],
      },
      zip_safe=False,
      install_requires=[
          'flask',
          'flask-wtf',
          'flask-bootstrap',
          'flask-basicauth',
          'pymongo',
          'pint',
          'numpy',
          'uncertainties',
          'bgmodelbuilder>=0.2',
      ],
      dependency_links=[
          'git+https://github.com/bloer/bgmodelbuilder@v0.2#egg=bgmodelbuilder-0.2',
      ],
)
