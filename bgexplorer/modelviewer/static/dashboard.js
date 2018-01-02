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

//top-level crossfilter instance
dashboard.cf = crossfilter();
//crossfilter dimensions and groups. Will be keyed by the column headings
dashboard.cfdimensions = {}
dashboard.cfgroups = {}
dashboard.cfgroupAll = dashboard.cf.groupAll();
dashboard.cffilters = {}
//d3.js hierarchies. will be keyed by the column headings
dashboard.hierarchies = {}
//sorting functions for groups
dashboard.groupsort = {}

dashboard.valuetypes = []

//list of interactive display objects that should be updated when filters change
dashboard.displays = {
    'tables': [],
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
    
var splitkey = '//';


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
            console.error("Error while building hierarchy for group "
                          +g+": "+error);
        }
        var sortlist = dashboard.groupsort[g];
        if(sortlist){
            dashboard.hierarchies[g].sort(function(a,b){
                return sortlist.indexOf(a.id) - sortlist.indexOf(b.id);
            });
        }
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
    //recursive function to add nested rows
    function addrow(node){
        var row = tbody.append("tr")
            .datum(node)
            .classed("grouprow depth"+node.depth,true);
        row
          .selectAll("td").data(allcols).enter().append("td")
            .attr("class",function(d,i){ return i ? "valcell" : "groupcell"; })
            .text(function(d,i){
                if(i) return "";
                var id = d3.select(this.parentNode).datum().id;
                return id == splitkey ? "Total" : id.split(splitkey).pop();
            })
            
        ;
        if(node.children){
            row.classed("haschildren",true);
            node.children.forEach(addrow);
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
        table.select("tbody").selectAll("tr td.valcell")
            .filter(function(d){ return d == val; })
            .text(function(d){ 
                return d3.select(this.parentNode).datum().value.toPrecision(2); 
            })
        ;
    });
    
};


})( window.bgexplorer = window.bgexplorer || {});
