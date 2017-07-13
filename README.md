# bgmodelbuilder
Tools to construct a model for sources of radioactive backgrounds in a low radioactivity dertector system

## Overview
A common problem in detector systems is estimating the background. For radiation detectors, often the background is dominated by a few sources, and this is relatively easy to determine.  However, for ultra-low background radiation detectors, even small components can have a large effect. Keeping track of all these components, and multiple radioactivity specifications for each one can become an accounting nightmare.  

This module provides a suite of classes that can be used to aid in this task. At it's base, a background model is a hierarchy of components (screws, circuitboards, flanges, cryostats, wires), each with a list of specifications (bulk U238 rates, dust on surfaces), and normalized by an efficiency factor, usually derived from simulations (not part of this module). 

## Classes
### component.Component
A component usually represents a physical object: a screw, wire, bucket, etc. Components have a name and optional description and comment, and store related physical quanitities needed to normalize radioactive emissions: 
 - material
 - mass
 - volume
 - surface\_in (inner surface area, for things like cans)
 - surface\_out (outer area for things like cans)
   - can also just be surface 
 - additional physical quanities can be specified by the 'physical_quantities' parameter. 
 
Components will also contain a list of CompSpecs that define the radioactivity levels. 

Additional information like part numbers, vendors, dates received, links to tracking information, etc, can be provided in the 'extrainfo' parameter. 

### component.Assembly
An assembly has a name, optional desription and comment, and contains a list of sub-components and/or sub-assemblies.  Each subcomponetn can also be given a weight, typically used for multiple part numbers (e.g. a flange assembly may have 20 bolts as subcomponents.)  Or, if a 'wire' component is specified given with a mass of 1 g/meter, the weight given might be 30 meters. 

### compspec.ComponentSpec

*in progress*
