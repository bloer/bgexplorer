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



//parse the rows in the tsv datatable. Should be passed as the second argument
//to d3.tsv
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
    var out = { 'ID': row.ID, 'groups': {}, 'values': {} };
    groups.forEach(function(g){ out.groups[g] = row['G_'+g] });
    dashboard.valuetypes.forEach(function(v){ out.values[v] = +row['V_'+v] });
    return out;
};
    
var splitkey = '___';

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
        dashboard.cfdimensions[g] = dashboard.cf.dimension(function(d){
            return d.groups[g];
        });
        dashboard.cfgroups[g] = dashboard.cfdimensions[g].group()
            .reduce(reduceAdd, reduceRemove, reduceInitial);
    });
    dashboard.cfgroupAll.reduce(reduceAdd, reduceRemove, reduceInitial);
    
    //process the data
    dashboard.cf.add(rows);
    
    //now create d3 hierarchies for each group
    function flatparentId(d){ return d.key == splitkey ? null : splitkey; }
    function topparentId(d){ 
        return d.key.split(splitkey).slice(0,-1).join(splitkey); 
    }
    function parentId(d){
        if(d.key == splitkey) return null; 
        split = d.key.split(splitkey).slice(0,-1);
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
            var split = leaf.key.split(splitkey);
            for(var depth=0; depth < split.length-1; ++depth){
                var newkey = split.slice(0,depth+1).join(splitkey);
                if(depth == 0)
                    topnodes.add(newkey);
                addnodes.add(newkey);
            }
        });
        if(topnodes.size() != 1)
            addnodes.add(splitkey);
        var allnodes = leaves.concat(addnodes.values().map(
            function(d){ return {key:d }; } ));;
        
        var pid = parentId;
        if(addnodes.size() == 0) pid = flatparentId;
        if(topnodes.size() == 1) pid = topparentId;
        try{
            dashboard.hierarchies[g] = d3.stratify()
                .id(function(d){ return d.key; }).parentId(pid)(allnodes);
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
            node.name = node.data.key.split(splitkey).pop();
            if(node.name == "" || node.name == splitkey) node.name = "Total";
            node.id = (g+splitkey+node.id).replace(/[^A-z0-9_-]/g,'_');
            if(node.parent){
                node.siblings = node.parent.children.length;
                node.index = node.parent.children.indexOf(node);
                node.colorStart = (node.index+0.05) / node.siblings;
                node.colorEnd = node.colorStart + 0.9/node.siblings;
                if(node.parent.color){
                    node.colorStart = node.parent.colorStart + node.colorStart * (node.parent.colorEnd - node.parent.colorStart);
                    node.colorEnd = node.parent.colorStart + node.colorEnd * (node.parent.colorEnd - node.parent.colorStart);
                }
                node.color = d3.interpolateCool(node.colorStart*0.9+0.1);
            }
            else{
                node.siblings = 1;
                node.index = null;
                node.color = null;
            }
        });
    });
    dashboard.dataloaded = true;
    onload.forEach(function(callback){ callback(); });
}

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
            .datum(function(d){ return {'group': node, 'val': d }; })
            .attr("class",function(d,i){ return i ? "valcell" : "groupcell"; })
            .text(function(d,i){
                if(i) return "";
                return d.group.name;
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
    var grouproot = table.select("tbody").datum();
    table.selectAll("thead tr th.valhead").each(function(val){
        grouproot.sum(function(node){
            return node.value ? node.value[val] : 0;
        });
        
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
                return d.group.value.toExponential(dashboard.config.titleprecision); 
            })
            .text(function(d){
                var myval = d.group.value;
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



dashboard.buildchart = function(parent, group, valtype, width, id){
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
    var container = d3.select(parent)
      .append("div").attr("class","bgexplorer-chart-container").style("width","100%")
        .datum(group);
    
    container.append("span").attr("class","bgexplorer-chart-title")
        .text(function(d){ return d; });
    
    width = width || $(container.node()).width() || 400;
    //width *= 0.95;
    
    var chart = container
      .append("svg")
        .attr("class","bgexplorer-chart")
        .attr("width",width)
        .attr("height",width)
      .append("g").datum({groupname:group, group: dashboard.hierarchies[group], val:valtype})
        .attr("class","bgexplorer-chart-window")
        .attr("width",width)
        .attr("height",width)
        //.attr("transform","translate("+width/2+","+width/2+")")
    ;
    dashboard.displays.charts.push(chart);
    dashboard.updatechart(chart);
    return chart;
};

dashboard.updatechart = function(chart, valtype){
    var chartdata = chart.datum();
    valtype = valtype || chartdata.val;
    chartdata.val = valtype;
    var groupname = chartdata.groupname;
    var width = parseInt(chart.attr("width"));
    var data = chartdata.group.sum(function(node){ return node.value ? node.value[valtype] : 0; });
    //scale the data so that we're zoomed in and cut off the total
    var maxdepth = data.height;
    var height = width; 
    width *= (1+maxdepth) / Math.min(maxdepth,3);
    d3.partition().size([height, width]).round(true).padding(1)(data);
    data.descendants().forEach(function(d){ 
        var w = d.y1 - d.y0; 
        d.y1 -= w; d.y0-=w;
    });    
    var nodes = chart.selectAll(".node")
      .data(data.descendants().filter(function(d){ return d.depth>0 && d.x1-d.x0>1; }),
           function(d){ return d.id; });
    var enter = nodes.enter().append("g")
        .attr("class",function(d){ return "node" + (d.children ? " branch": " leaf"); })
        .attr("transform",function(d){ return "translate("+d.y0+","+d.x0+")"; })
        .style("opacity",0);
    enter.append("rect")
        .attr("id",function(d){ return "rect-"+d.id; })
        .attr("width", 0)
        .attr("height", 0)
        .style("fill",function(d){ return d.color; }).style("opacity",0.6);
    enter.append("clipPath")
        .attr("id", function(d) { return "clip-" + d.id; })
      .append("use")
        .attr("xlink:href", function(d) { return "#rect-" + d.id + ""; });
    enter.append("text")
        .attr("x",3).attr("y",13)
        .attr("clip-path",function(d){ return "url(#clip-"+d.id+")";})
        .text(function(d){ return d.name });
    enter.append("title").text(function(d){ return d.name; });

    var merge = nodes.merge(enter);
    merge.selectAll("title").text(function(d){ return d.name + ": "+d.value.toExponential(5); });
    merge.transition().delay(5).duration(500)
        .attr("transform",function(d){ return "translate("+d.y0+","+d.x0+")"; })
      .selectAll("rect")
        .attr("width", function(d) { return d.y1 - d.y0; })
        .attr("height", function(d) { return d.x1 - d.x0; });
    
    nodes.exit().transition().delay(5).duration(400).style("opacity",0).remove();
    enter.transition().delay(400).duration(400).style("opacity",1);
    
};



})( window.bgexplorer = window.bgexplorer || {});