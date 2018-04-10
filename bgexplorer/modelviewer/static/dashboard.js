/**@file dashboard.js
   Creates the 'bgexplorer.dashboard' namespace. This will load the model's 
   datatable TSV
   export from the given endpoint and create a series of crossfilter groups
   and d3.js hierarchies based on the column headings. 
   
   This library requires both d3.js and crossfilter and must be loaded
   after them. 
*/

(function(bgexplorer){
//set up the 'dashboard' sub-namespace
bgexplorer.dashboard = bgexplorer.dashboard || {}
dashboard = bgexplorer.dashboard

//various configuration settings can be changed here
dashboard.config = {
    'tableprecision': 2,
    'tabledecimals':  3,
    'titleprecision': 5,
    'defaulttabledepth': 1,
    'maxchartdepth': 3,
    'minnodesize': 0.003,
    'mintextsize':0.05,
    'defaultcharttype': 'pie',
    'transitionduration':1000,
};

//top-level crossfilter instance
dashboard.cf = crossfilter();
//crossfilter dimensions and groups. Will be keyed by the column headings
dashboard.cfdimensions = {};
dashboard.cfgroups = {};
dashboard.cfgroupAll = dashboard.cf.groupAll();
dashboard.cffilters = {};
//d3.js hierarchies. will be keyed by the column headings
dashboard.hierarchies = {};
//sorting functions for groups
dashboard.groupsort = {};

dashboard.valuetypes = [];

//list of interactive display objects that should be updated when filters change
dashboard.displays = {
    'tables': [],
    'charts': [],
};

//register a function to be called when data finishes loading
var onload = []
dashboard.onLoad = function(callback){
    onload.push(callback);
    if(dashboard.dataloaded){
        callback();
        onload.pop();
    }
};


//parse a value column that has uncertainties in it
dashboard.parsevalstring = function(val){
    //strings are of the form "X+/-E" or "(X+/-E)eY"
    var expo="e0";
    if(val.startsWith("(")){
        var split = val.split("e");
        expo = "e"+split[1];
        val = split[0].slice(1,-1);
    }
    var split = val.split("+/-");
    if(split.length == 1)
        split[1] = "0";
    return [+(split[0]+expo), +(split[1]+expo)];          
};


//parse the rows in the tsv datatable. Should be passed as the second argument
//to d3.tsv
var splitkey = '___';
var groups = []; 
dashboard.parserow = function(row){
    if(groups.length == 0){//construct the list of groups
        for(var col in row){
            if(col.startsWith("G_"))
                groups.push(col.substr(2));
            else if(col.startsWith("V_"))
                dashboard.valuetypes.push(col.substr(2));
        }
    }
    var out = { 'ID': row.ID, 'groups': {}, 'values': {}, 'variance': {} };
    groups.forEach(function(g){ out.groups[g] = row['G_'+g].split(splitkey); });
    dashboard.valuetypes.forEach(function(v){ 
        parsed = dashboard.parsevalstring(row['V_'+v])
        out.values[v] = parsed[0];
        out.values[v+"_sig2"] = parsed[1]*parsed[1]; 
    });
    return out;
};
    

//take the list of objects returned from parserows and construct the crossfiler
// and d3 structures
dashboard.processtable = function(error,rows){
    if(error){alert(error); throw error;}
    
    dashboard.data = rows
    
    var first = rows[0];
    if(groups.length == 0){
        //we didn't build up the groups list
        groups = keys(first.groups);
        dashboard.valuetypes = keys(first.values);
    }
    
    //crossfilter group reduce functions
    function reduceInitial(){ return {count:0}; }
    function reduceAdd(p, v){ 
        for(var val in v.values){
            p[val] = (val in p ? p[val] : 0.) + v.values[val];
        }
        p.count += 1;
        return p;
    }
    function reduceRemove(p,v){
        for(var val in v.values){
            p[val] = p[val] - v.values[val];
        }
        p.count -= 1;
        return p;
    }

    //create a crossfilter dimension and group for each group
    groups.forEach(function(g){
        ['','filter_'].forEach(function(prefix){
            dashboard.cfdimensions[prefix+g] = dashboard.cf.dimension(function(d){
                return d.groups[g];
            });
        });
        dashboard.cfgroups[g] = dashboard.cfdimensions[g].group()
            .reduce(reduceAdd, reduceRemove, reduceInitial);
        dashboard.cffilters[g] = [];
    });
    dashboard.cfgroupAll.reduce(reduceAdd, reduceRemove, reduceInitial);
    
    //process the data
    dashboard.cf.add(rows);
    
    //save the totals
    dashboard.totalrates = jQuery.extend(true,{},dashboard.cfgroupAll.value());
    
    //now create d3 hierarchies for each group
    function flatparentId(d){ return d.key == [splitkey] ? null : splitkey; }
    function topparentId(d){ 
        return d.key.slice(0,-1).join(splitkey); 
    }
    function parentId(d){
        if(d.key == [splitkey]) return null; 
        split = d.key.slice(0,-1);
        if(split.length == 0) return splitkey;
        return split.join(splitkey);
    }

    groups.forEach(function(g){
        var leaves = dashboard.cfgroups[g].all();
        //if the group is nested, we need to create dummy nodes for the
        //intermediate entries
        var addnodes = d3.set();
        var topnodes = d3.set();
        leaves.forEach(function(leaf){
            for(var depth=0; depth < leaf.key.length-1; ++depth){
                var newkey = leaf.key.slice(0,depth+1).join(splitkey);
                if(depth == 0)
                    topnodes.add(newkey);
                addnodes.add(newkey);
            }
        });
        if(topnodes.size() != 1)
            addnodes.add([splitkey]);
        var allnodes = leaves.concat(addnodes.values().map(
            function(d){ return {key:d.split(splitkey)}; }) );
        
        var pid = parentId;
        if(addnodes.size() == 0) pid = flatparentId;
        if(topnodes.size() == 1) pid = topparentId;
        try{
            dashboard.hierarchies[g] = d3.stratify()
                .id(function(d){ return d.key.join(splitkey); }).parentId(pid)(allnodes);
        }catch(error){
            var msg = "Error while building hierarchy for group "+g+": "+error;
            console.error(msg);
            alert(msg);
            return;
        }
        var root = dashboard.hierarchies[g];
        //sort them based on user provided values or else by value
        var sortlist = dashboard.groupsort[g];
        if(sortlist){
            root.sort(function(a,b){
                return sortlist.indexOf(a.id) - sortlist.indexOf(b.id);
            });
        }
        else{
            //sort by the sum over all values
            root.sum(function(node){ 
                return node.value ? Object.values(node.value).reduce(function(a,b){ return a+b; }) : 0;
            }).sort(function(a,b){ return b.value - a.value; });
            
        }
        //add some additional useful info
        root.each(function(node){ 
            node.name = node.data.key[node.data.key.length-1];
            if(node.name == "" || node.name == splitkey) node.name = "Total";
            node.id = (g+splitkey+node.id).replace(/[^A-z0-9_-]/g,'_');
            node.group = g;
            node.dimension = dashboard.cfdimensions[g];
            node.filter = dashboard.cffilters[g];
            node.filterdimension = dashboard.cfdimensions['filter_'+g]
            if(node.parent){
                node.siblings = node.parent.children.length;
                node.index = node.parent.children.indexOf(node);
                node.colorStart = (node.index+0.05) / node.siblings;
                node.colorEnd = node.colorStart + 0.9/node.siblings;
                if(node.parent.color){
                    node.colorStart = node.parent.colorStart + node.colorStart * 
                        (node.parent.colorEnd - node.parent.colorStart);
                    node.colorEnd = node.parent.colorStart + node.colorEnd * 
                        (node.parent.colorEnd - node.parent.colorStart);
                }
                node.color = d3.hcl(d3.interpolateCool(node.colorStart*0.9+0.1)).brighter(0.7);
            }
            else{
                node.siblings = 1;
                node.index = null;
                node.color = null;
            }
        });

        //add a function to sum all of the data 
        root.sumAll = function(){
            return this.eachAfter(function(node){
                var valueAll = node.data.value || {};
                if(node.children){
                    node.children.forEach(function(child){
                        for(var val in child.valueAll){
                            valueAll[val] = child.valueAll[val] + (valueAll[val] || 0);
                        }
                    });
                }
                node.valueAll = valueAll;
            });
        };
        root.sumAll();
    });
    dashboard.dataloaded = true;
    onload.forEach(function(callback){ callback(); });
    //update stuff for filter info if defined
    var filterinfo = d3.select("#dashboard-filterinfo")
        .html(function(){
            return "<h4>Filter Info</h4>" 
                + "<span class='filterstat' id='dashboard-records'>0</span> "
                + "records pass all filters. <br>"
                + "<span class='filterstat' id='dashboard-rate'>0</span> "
                + "rate pass all filters. <br>"
            ;
        });
    filterinfo.append("h5").text("Active Filters")
      //.append("small")
      .append("a").text(" reset all").attr("href","#").on("click",function(){
          d3.event.preventDefault();
          //clear all the filter arrays
          Object.values(dashboard.cffilters).forEach(function(a){ a.length = 0; });
          dashboard.updateFilters();
      });
        
    filterinfo.append("ul").attr("id","dashboard-activefilters")
        .attr("class","list-unstyled")
      .selectAll("li")
        .data(Object.entries(dashboard.cffilters))
        .enter().append("li").text(function(d){ return d[0]+": "; }).append("ul");
    /*
      //this isn't working yet
    var form = filterinfo.append("form")
        .attr("id","dashboard-newfilterform")
        .attr("class","form form-horizontal")
        .on("submit",function(){
            d3.event.preventDefault();
        });
    form.append("h5").text("Add filter");
    form.append("select").selectAll("option").data(Object.keys(dashboard.cffilters))
      .enter().append("option")
        .text(function(d){ return d; })
        .attr("value",function(d){ return d; });
    form.append("input").attr("type","text");
    */
}

/* Update the filters for a node from a click.  Holding the shift key will combine 
   the selections. Holding ctrl will invert the filter (i.e. remove the group rather 
   than select it.) Shift and Ctrl can be used together to remove multiple groups
*/
var shiftRegistered = false;
function modifyFilters(node){
    d3.event.preventDefault();
    d3.select(this).classed("selected",true);
    
    //push the new selection on the stack
    node.filter.push([d3.event.ctrlKey, node.data.key]);
    if(d3.event.shiftKey){
        //combine the filter with others and wait for shift key to be released
        if(!shiftRegistered){
            shiftRegistered = true;
            d3.select("body").on("keyup",function(){
                if(d3.event.key == "Shift"){
                    shiftRegistered = false;
                    dashboard.updateFilters();
                }
            });
        }
    }
    else{ //things take place immediately
        while(node.filter.length > 1)
            node.filter.shift();
        dashboard.updateFilters(node.group);
    }
}

//todo: go back to storing strings since we have ot do this slow
/* each test entry is a 2-tuple, with the first entry declaring whether it is an 
   acceptance check (0) or exclusion (1). This logic can probably be improved on for clarity
*/

function filterKeys(groupname){
    var tests = dashboard.cffilters[groupname];
    return function(record){
        var npasschecks=0, npass=0;
        for(var i in tests){
            var exclude = tests[i][0];
            var match = record.slice(0,tests[i][1].length).toString() == 
                tests[i][1].toString();
            if(exclude && match) return false;
            if(!exclude){
                npasschecks += 1;
                npass += match;
            }
        }
        return npasschecks == 0 || npass > 0;
    };
}

dashboard.updateFilters = function(group){
    for(var groupname in dashboard.cffilters){
        if(!group || group == groupname)
            dashboard.cfdimensions['filter_'+groupname].filter(filterKeys(groupname));
    }
    dashboard.updateall();
};


/* Create a table with group values for rows and reduced values for columns.
   Args:
       parent: d3 selector for the parent div to put the table in
       group: string name of group to use for rows.  If the grouping is nested,
              subgroups will be expandable
       cols: list of string columns names. Should correspond to entries in 
             each node's `value` object
       id: id to use for this table; if not set, will be set to parent.id+_table
*/
dashboard.buildtable = function(parent, group, cols, id){
    //make sure the group exists
    if(!dashboard.hierarchies[group]){
        var error = "dashboard.buildtable: unknown group name "+group;
        console.error(error);
        throw error;
    }
    cols = cols || dashboard.valuetypes;
    var table = d3.select(parent)
      .append("table")
        .classed("table table-condensed bgexplorertable",true);
    id = id || d3.select(parent).attr('id') + "_table";
    if(id) table.attr("id",id);
    dashboard.displays.tables.push(table);
    
    //build up the table head
    var allcols = [group].concat(cols);
    table.append("thead").append("tr")
        .selectAll("th").data(allcols).enter()
      .append("th")
        .text(function(d){ return d; })
        .attr("class",function(d,i){ return i ? 'valhead' : 'grouphead'; })
    ;
    
    //create all the cells only once
    var tbody = table.append("tbody").datum(dashboard.hierarchies[group]);
    //toggle nested rows' visibility
    function togglerowexpanded(row, newstate){
        var row = d3.select(row);
        var children = d3.select(row.node().parentNode)
          .selectAll("tr.grouprow").filter(function(d){ 
              return d.parent == row.datum(); 
          });
        
        if(!newstate){
            //we want to toggle our own state
            if(row.classed("expanded")){
                newstate = "closed";
                row.classed("expanded",false);
                children.classed("hide",true);
            }
            else{
                newstate = "expanded";
                row.classed("expanded",true);
                children.classed("hide",false);
            }
        }
        else{
            children.classed("hide",!(newstate == "expanded" && row.classed("expanded")));
        }
        children.filter(".haschildren").each(function(d){ togglerowexpanded(this, newstate); });
    }
    
    //recursive function to add nested rows
    function addrow(node){
        var opendepth = dashboard.config.defaulttabledepth;
        var row = tbody.append("tr")
            .datum(node)
            .classed("grouprow depth"+node.depth,true)
            .classed("hide",node.depth>opendepth);
        row
          .selectAll("td").data(allcols).enter().append("td")
            .datum(function(d){ return {'node': node, 'val': d }; })
            .attr("class",function(d,i){ return i ? "valcell" : "groupcell"; })
            .text(function(d,i){
                if(i) return "";
                return d.node.name;
            })
            
        ;
        if(node.children){
            row.classed("haschildren",true)
                .classed("expanded",node.depth<opendepth);
            childrows = node.children.map(addrow);
            row.select("td.groupcell")
              .append("span").attr("class","caret expander")
                .on("click", function(){
                    togglerowexpanded(this.parentNode.parentNode);
                });
        }
        else{
            row.classed("leaf",true);
        }
        return row;
    }
    addrow(dashboard.hierarchies[group]);
    dashboard.updatetable(table);
    return table;
};

//update the values in the given table
dashboard.updatetable = function(table){
    var grouproot = table.selectAll("tbody").datum();
    table.selectAll("thead tr th.valhead").each(function(val){
                
        //determine whether to use floating point or exp notation
        var total = grouproot.value;
        var totalpower = Math.floor(Math.log10(total));
        //TODO: make these configurable
        
        var decimals = dashboard.config.tabledecimals;
        var precision = dashboard.config.tableprecision;
        var useexpo = totalpower > 3 || totalpower < -1;
        
        var exponent = 2-totalpower;
        var multiplier = 10**(exponent);
        
        
        table.select("tbody").selectAll("tr td.valcell")
            .filter(function(d){ return d.val == val; })
            .attr("title",function(d){ 
                var precision = dashboard.config.titleprecision;
                return d.node.valueAll[val].toExponential(precision)
                    + " +/- "
                    + Math.sqrt(d.node.valueAll[val+"_sig2"]).toExponential(precision); 
            })
            .text(function(d){
                var myval = d.node.valueAll[val];
                if(myval == 0)
                    return "";
                if(useexpo)
                    myval *= multiplier;
                var mypower = Math.floor(Math.log10(myval));
                var sigdigs = myval.toExponential(precision-1).substr(0,precision);
                var fixed = parseFloat(myval.toExponential(precision-1)).toFixed(decimals);
                //replace trailing zeros after the decimal point
                var sigdecs = Math.min(Math.max(precision-mypower-1,0),decimals);
                var cut = decimals-sigdecs;
                var length = fixed.length;
                var result =  fixed.substr(0,length-cut).padEnd(length);
                return useexpo ? result+" E"+(-exponent).toString() : result;
            })
        ;
    });
    
};



dashboard.buildchart = function(parent, group, valtype, charttype, width, id){
    //TODO: move error checking to a dedicated function
    //make sure the group exists
    if(!dashboard.hierarchies[group]){
        var error = "dashboard.buildchart: unknown group name "+group;
        console.error(error);
        throw error;
    }
    if(dashboard.valuetypes.indexOf(valtype) == -1){
        var error = "dashboard.buildchart: unknown value type "+valtype;
        console.error(error);
        throw error;
    }

    if(charttype != "icicle" && charttype != "pie"){
        if(charttype)
            console.warn("Unknown chart type "+charttype+": defaulting to "+dashboard.config.defaultcharttype);
        charttype = dashboard.config.defaultcharttype;
    }
    var container = d3.select(parent)
      .append("div").attr("class","bgexplorer-chart-container").style("width","100%")
        .datum(group);
    
    id = id || d3.select(parent).attr('id') + "_chart";
        
    var display = container.append("div").attr("class","bgexplorer-chart-title clearfix")
        .attr("id",id)
        .style("width","100%")
        .text(function(d){ return d; })
      .append("span")
        .attr("class","bgexplorer-selection-display pull-right")
        .attr("id",id+"-selection-display");
    
    width = width || $(container.node()).width() || 400;
    //width *= 0.95;
    
    var chart = container
      .append("svg")
        .attr("class","bgexplorer-chart")
        .attr("width",width)
        .attr("height",width)
      .append("g").datum({groupname:group, 
                          group: dashboard.hierarchies[group], 
                          val:valtype, 
                          type:charttype,
                          display:display,
                         })
        .attr("class","bgexplorer-chart-window")
        .attr("width",width)
        .attr("height",width)
        .attr("transform",charttype == "pie" ? "translate("+width/2+","+width/2+")" : null)
    ;
    dashboard.displays.charts.push(chart);
    //dashboard.updatechart(chart);
    return chart;
};

var arc = d3.arc()
        .startAngle(function(d){ return d.x0; })
        .endAngle(function(d){ return d.x1; })
        .innerRadius(function(d){ return d.y0; })
        .outerRadius(function(d){ return d.y1; })
        .cornerRadius(0);
    
    
function arcTween(d){
	var end = {x0:d.x0, y0:d.y0, x1:d.x1, y1:d.y1};
    var start = end;
    if(d.previousVals)
        start = d.previousVals;
	return d3.interpolate(start,end);
}
function arcTweenD(d){
	return function(t){ return arc(arcTween(d)(t)); };
}
function rotateTween(d){
    return function(t){ 
        var dd = arcTween(d)(t);
        var centroid = arc.centroid(dd);
        var angle = Math.atan(centroid[1]/centroid[0])*180/Math.PI - 90;
        if(dd.y1-dd.y0 > 0.5*(dd.y0+dd.y1)*(dd.x1-dd.x0)) angle -= 90;
        if(angle < -90 || angle > 90) angle += 180;
        return "rotate("+angle+" "+centroid[0]+" "+centroid[1]+")";
    };
}
	

function doanimation(transition, data, pie){
    transition.duration(dashboard.config.transitionduration);
    transition
      .selectAll("rect.bgexplorer-data-shape")
        .attr("x", function(d){ return d.y0; })
        .attr("y", function(d){ return d.x0;})
        .attr("width", function(d) { return d.y1 - d.y0; })
        .attr("height", function(d) { return d.x1 - d.x0; });
    transition.selectAll(".bgexplorer-data-shape.arc")
        .attrTween("d",arcTweenD);
    if(pie){
        var mintext = dashboard.config.mintextsize;
        transition.selectAll("text")
          .filter(function(d){ return d.value / data.value >= mintext; })
            .attr("display",null)
            .attrTween("x",function(d){
                return function(t){ return arc.centroid(arcTween(d)(t))[0]; };
            })
            .attrTween("y",function(d){
                return function(t){ return arc.centroid(arcTween(d)(t))[1]; };
            })
            .attrTween("transform",rotateTween)
        ;
        transition.selectAll("text").filter(function(d){ 
            return d.value/data.value < mintext; 
        }).attr("display","none");
    }
    transition.on('end',function(d){ d.previousVals = {x0: d.x0, x1: d.x1, 
                                              y0: d.y0, y1: d.y1}; 
                                    });
}

//TODO: Make this more efficient!
dashboard.updatechart = function(chart, valtype){
    var chartdata = chart.datum();
    valtype = valtype || chartdata.val;
    chartdata.val = valtype;
    var groupname = chartdata.groupname;
    var pie = chartdata.type == "pie";
    var width = parseInt(chart.attr("width"));
    var data = chartdata.group;//.sum(function(node){ return node.value ? node.value.count : 0; });
    //scale the data so that we're zoomed in and cut off the total
    var maxdepth = data.height+1;
    var height = width; 
    //determine the innermost ring to show
    var rootnode = data;
    var h = rootnode.height;
    while(true){ //maxdepth - mindepth > dashboard.config.maxchartdepth){
        if(!rootnode.children) break;
        var fullchild = rootnode.children.some(function(child){ //use some to short-circuit the loop
            if(child.valueAll.count == rootnode.valueAll.count){
                rootnode = child;
                return true;
            }
            return false;
        });
        if(!fullchild) break;
        h = rootnode.height; 
        if(rootnode.height < dashboard.config.maxchartdepth){
            h = rootnode.height+1;
            rootnode = rootnode.parent;
            break;
        }
        if(rootnode.height <= dashboard.config.maxchartdepth)
            break;
    }
    var mindepth = rootnode.depth+1;
    var rad = width/2 * (maxdepth) / Math.min(h,dashboard.config.maxchartdepth);
    //recalculate for the value we care about
    //data.sum(function(node){ return node.value ? node.value[valtype] : 0.; });
    data.each(function(node){ node.value = node.valueAll[valtype] || 0; });
    d3.partition()
        .size(pie ? [2*Math.PI, 0.99*rad] : [height, width])
        .round(false)
        .padding(0)
      (data);
    data.each(function(d){ 
        var w = d.y1 - d.y0; 
        d.y1 -= mindepth*w; d.y0-=mindepth*w;
        if(!d.previousVals)
            d.previousVals = {x0: d.x0, x1: d.x1, 
                              y0: d.y0, y1: d.y1}; 
    });    
    
    var nodes = chart.selectAll(".node")
      .data(data.descendants().filter(function(d){ 
          return d.depth>=mindepth && d.depth<=dashboard.config.maxchartdepth+mindepth-1 
              && d.value > 0
              && d.value/data.value>dashboard.config.minnodesize
              ; 
      }),function(d){ return d.id; });
    var enter = nodes.enter().append("g")
        .attr("class",function(d){ return "node" + (d.children ? " branch": " leaf"); })
        .attr("clip-path",function(d){ return "url(#clip-"+d.id+")";})
        //.style("opacity",0)
        .on("mouseenter", function(d){ 
            chartdata.display.text(d3.select(this).select("title").text());
        })
        .on("mouseleave",function(){ chartdata.display.text(null); })
        .on("click",modifyFilters);
           
    ;
    if(pie){
        enter.append("path")
            .attr("class","bgexplorer-data-shape arc")
            .attr("d",arc);
    }
    else{
        enter.append("rect")
            .attr("class","bgexplorer-data-shape rect")
            .attr("x", function(d){ return d.y0; })
            .attr("y", function(d){ return d.x0;})
            .attr("width", 0)
            .attr("height", 0);
    }
    enter.selectAll(".bgexplorer-data-shape")
        .attr("id",function(d){ return "shape-"+d.id; }) //todo: this needs to be globally unique
        .style("fill",function(d){ return d.color; })
        //.style("opacity",0.6);
    enter.append("clipPath")
        .attr("id", function(d) { return "clip-" + d.id; }) //todo: this needs to be globally unique
      .append("use")
        .attr("xlink:href", function(d) { return "#shape-" + d.id + ""; });
    enter
      .append("text")
        .attr("class","bgexplorer-chart-label")
        .attr("text-anchor","middle")
        .attr("dominant-baseline","central")
        .attr("y",5).attr("x",0)
        //.attr("clip-path",function(d){ return "url(#clip-"+d.id+")";})
        .attr("pointer-events", "none") //prevent stealing hover
        .text(function(d){ return d.name })
        
    ;
    enter.append("title").text(function(d){ return d.name; });
    var merge = nodes.merge(enter);
    merge.classed("selected",false)
      .selectAll("title")
        .text(function(d){ return d.name + ": "+d.value.toExponential(5); });
    merge.transition().call(doanimation, data, pie);
    nodes.exit().transition().call(doanimation, data, pie)
      .remove();
    
    
    //exit
        //.transition().delay(dashboard.config.transitionduration)
        //.duration(dashboard.config.transitionduration/2)
        //.style("opacity",0)
        //.remove();
    //enter.transition().delay(dashboard.config.transitionduration)
      //  .duration(dashboard.config.transitionduration).style("opacity",1);
    
    
};

var currentvaltype = null;
dashboard.updateall = function(valtype){
    if(valtype) currentvaltype = valtype;
    //update the hierarchy sums
    groups.forEach(function(g){
        dashboard.hierarchies[g].sumAll();
    });
    
    //update the displays
    dashboard.displays.tables.forEach(dashboard.updatetable);
    dashboard.displays.charts.forEach(function(chart){
        dashboard.updatechart(chart, valtype);
    })
    d3.select("#dashboard-records").text(function(){
        var totalrecords = dashboard.data.length;
        var filterrecords = dashboard.cfgroupAll.value().count;
        return filterrecords+" / "+totalrecords
            +" ("+(100*filterrecords/totalrecords).toFixed(1)+"%)";
    });
    
    d3.select("#dashboard-rate").text(function(){
        var totalrate = dashboard.totalrates[currentvaltype] || 0;
        var filterrate = dashboard.cfgroupAll.value()[currentvaltype] || 0;
        var unit = "";
        var unitoffset = currentvaltype.search(/\[.*\]$/);
        if(unitoffset != -1)
            unit = " "+currentvaltype.substring(unitoffset+1,currentvaltype.length-1);
        return filterrate.toPrecision(3)+" / "+totalrate.toPrecision(3) + unit
            +" ("+(100*filterrate/totalrate).toFixed(1)+"%)";
    });
    var li = d3.selectAll("#dashboard-activefilters li ul").selectAll("li")
        .data(function(d){ return d[1].map(function(dd,i){ 
            return {group:d[0], filterlist: d[1], test: dd, index: i}; 
        }); });
    li.exit().remove();
    li.enter().append("li").merge(li).text(function(d){ 
        return (d.test[0] ? "! ":"") + d.test[1][d.test[1].length-1]; })
      .append("a").attr("href","#")
      .append("span")
        .attr("class","glyphicon glyphicon-remove")
        .style("color","red")
        .on("click",function(d){
            d3.event.preventDefault();
            d.filterlist.splice(d.index,1);
            dashboard.updateFilters(d.group);
        }); 
    ;
    
};

})( window.bgexplorer = window.bgexplorer || {});
