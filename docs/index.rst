.. bgexplorer documentation master file, created by
   sphinx-quickstart on Thu Oct 19 09:19:30 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

===================
Background Explorer
===================

Overview
========
Background Explorer (*bgexplorer*) is a tool designed to model the radioactive backgrounds in particle detectors. It eases much of the tedious book-keeping and math involved in calculating a total radioactivity budget, and provides an interface to drill down into the individual contributions. 

There are three main components of *bgexplorer*: a detector model, a simulations database, drill-down views. 

Detector Model
--------------
The detector model is used to calculate the rate of radioactive emissisions emanating from any given part of a detector setup. The model consists of Components that are arranged into a hierarchy of Assemblies. Components represent physical parts: screws, wires, pressure vessels, pipes, etc. Assemblies are logical groupings of Components (or sub-Assemblies) with weights. E.g., a Widget may contain 3 gears, 2 axles, and 5 screws, and a Thingajig may contain a chassis, 3 wheels and 4 widgets. Much like CAD software, Components and Assemblies may be placed into multiple Assemblies, so that changing the definition of a common part in one place will update the definition everywhere.   

Components have physical quantities like material, mass, and surface area. They also have one or more EmissionSpecs for their level of radioactive contamination. The most common are bulk contamination of common isotopes like U-238, Th-232, and K-40 measured by some sort of assay process.  EmissionSpecs may also be provided for surface contamination, and estimated rates based on exposure to cosmic rays or radon-laden air are also provided. Each EmissionSpec is normalized by the relevant physical quantity of the component to calculate the absolute emission rate (e.g., a pipe with 1 Bq/kg U-238 spec massing 10 kg has 10/s decay rate).  

Simulation Database
-------------------
The background event rate from a given component *i* is

.. math::
   R_i = \sum_j E_{i,j} \cdot P_{i,j}

where :math:`E_{i,j}` is the absolute emission rate of spec *j* and :math:`P_{i,j}` is the probability for characteristic radiation of type *j* emitted from the location of component *i* to cause a background event in the detector. *P* depends on a number of factors including the distance from the detector, materials between the source point and detector, and the definition of a background event. The most common method of estimating *P* is to perform a Monte Carlo simulation.  

For a complex detector design with hundreds of components each having tens of emission speccs, we would require thousands of different datasets for selecting the correct :math:`P_{i,j}`. *bgexplorer* assumes that these datasets will be provided in the form of a simulations database. The user must write a class inheriting from SimulationDB and overload methods to connect Components with the appropriate datasets.  The user's SimulationsDB also defines the different categories of events that will be available for inspection in the drill-down interface, e.g. all events, events within fiducial volume, sub-threshold events, etc. See :doc:`userhooks` for more details. 


Contents
========
.. toctree::
   :maxdepth: 1
   
   installation
   modeleditor
   userhooks
   bgexplorer
   bgmodelbuilder

..
  Indices and tables
  ==================

  * :ref:`genindex`
  * :ref:`modindex`
  * :ref:`search`
