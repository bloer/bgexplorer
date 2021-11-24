"""
@file widgets.py
@author: bloer

Defines a few custom widgets for rendering dynamic elements

"""

#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
import json
import types
from collections import namedtuple

from wtforms.widgets import (html_params, HTMLString, HiddenInput, TextInput,
                             CheckboxInput, RadioInput, TextArea)
from wtforms.utils import unset_value

from flask_bootstrap import is_hidden_field_filter

def is_hidden_field(field):
    return (is_hidden_field_filter(field)
            or isinstance(field.widget, HiddenInput)
            or getattr(field.widget,'input_type', None) == 'hidden')


class TableRow(object):
    """Render a FormField as a row in a table"""
    def __call__(self, field, **kwargs):
        html = []
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('data-prefix', field.name)
        render_kw = kwargs.pop('render_kw',{})
        html.append("<tr %s>"%html_params(**kwargs))
        for subfield in field:
            html.append('<td data-column="%s"'%subfield.short_name)
            if is_hidden_field(subfield):
                html.append(' class="hide"')
            html.append('>%s</td>'%subfield(**render_kw))
        #add remove button
        html.append('<td data-column="delete">'
                    '<a onclick="$(this).parents(\'tr\')'
                    '.fadeOut(function(){$(this).remove();});">')
        html.append('<span class="text-danger linklike glyphicon '
                    'glyphicon-remove"></span>')
        html.append('</a></td>')
        html.append("</tr>")
        return HTMLString(''.join(html))

class SortableTable(object):
    """
    Create a table with sortable rows that returns the data as
    a JSON string
    """

    def __call__(self, field, **kwargs):
        html = []
        id = kwargs.setdefault('id', field.id)
        #we need a bound subfield to make the table columns
        boundform = field.unbound_field.bind(
            form=None, prefix=field._prefix, _meta=field.meta,
            translations=field._translations,
            name=field.short_name,
            id=field.id+'-template')
        boundform.process(None, unset_value)

        #now make the table
        #Flask_Bootstrap wants to give this form-control class...
        kwargs['class'] = kwargs.get('class','').replace('form-control','')
        kwargs['class'] += ' '+kwargs.get('_class','')
        html.append("<table %s>"%html_params(**kwargs));
        html.append("<thead><tr>")
        #should inherit from FieldList...
        for subfield in boundform:
            if not is_hidden_field(subfield):
                html.append('<th title="%s">%s</th>'%(subfield.description,
                                                      subfield.label))
        #one more to hold the remove button
        html.append("<th></th>");
        html.append("</tr></thead>")
        #now loop through the subforms
        html.append('<tbody class="sortable">')
        for entry in field:
            html.append(TableRow()(entry, **{'data-prefix':field.name}))

        #make a fake hidden form for cloning
        html.append(TableRow()(boundform, render_kw={'disabled':'disabled'},
                               **{'class':'hide template',
                                  'data-prefix':field.name}))
        html.append("</tbody></table>")
        #add an 'add new' button
        html.append('<button type="button" class="btn text-primary" ')
        html.append('onclick="addrow(\'#%s\')" >'%id)
        html.append('<span class="glyphicon glyphicon-plus"></span>')
        html.append(' Add')
        html.append('</button>')
        html.append(
        """<script type="text/javascript">
            function setindex(index, row){
                row = $(row);
                row.data('index',index);
                row.attr('id', row.data('prefix')+'-'+index);
                var inputs = row.find("[name]").attr("disabled",false);
                inputs.each(function(){
                  var name = row.data('prefix') + '-' + index + '-'
                      + $(this).parents("td").data('column');
                  $(this).attr('id',name).attr('name',name);
                });
            }
            function addrow(obj, valsFrom){
                obj = $(obj);
                var row = obj.find("tr.template").clone()
                    .removeClass('hide').removeClass('template');
                if(valsFrom){
                    valsFrom=$(valsFrom);
                    //copy data-* for each column we care about
                    row.children("td").each(function(){
                        var name=$(this).data('column');
                        if(!name) return;
                        var copyval = valsFrom.data(name);
                        if(!copyval) return;
                        $(this).find("input, select").val(copyval);
                        $(this).children().css("display","none");
                        $("<p class='form-control-static'>")
                            .text(copyval)
                            .appendTo($(this));
                    });
                    $("<div>")
                      .attr("class","alert alert-success")
                      .css("position","absolute")
                      .css("width",valsFrom.width())
                      .css("height",valsFrom.height())
                      .appendTo("body")
                      .offset(valsFrom.offset())
                      .animate({
                          'left':obj.offset().left,
                          'top':obj.offset().top + obj.height(),
                      },function(){
                          obj.children('tbody').append(row);
                          $(this).remove();
                      });
                }
                var index = obj.find("tbody tr").not('.template').size();
                setindex(index, row);
                if(!valsFrom)
                    obj.children('tbody').append(row);
            }
            function sortIndices(container){
                 $(container).children().not('.template').each(setindex);
            }
        </script>
        """)
        return HTMLString(''.join(html))


class InputChoices(TextInput):
    def __init__(self, choices=None):
        self.choices = choices or []

    def __call__(self, field, **kwargs):
        html = []
        html.append('<div class="dropdown">')
        html.append('<div class="input-group" data-toggle="dropdown">')
        html.append(super().__call__(field, **kwargs))
        html.append('<div class="input-group-btn">')
        html.append('<button class="btn dropdown-toggle hide" type="button">')
        #html.append('<span class="caret" style="width:0.5em;"></span>')
        html.append('</button></div>')
        html.append('</div>')
        html.append('<ul class="dropdown-menu">')
        for choice in self.choices:
            html.append('<li><a href="javascript:void(0)" onclick='
                        '"$(this).parents(\'.dropdown\').find(\'input\')'
                        '.val($(this).text());">'
                        '%s</a></li>'%choice)
        html.append('</ul></div>')
        return HTMLString(''.join(html))



class StaticIfExists(object):
    """ If the value is already defined, render it as static
    only create a non-hidden input if _value is empty
    Args:
       default (widget): Widget to render if value is not set
    """
    def __init__(self, default=TextInput()):
        self.default = default

    def __call__(self, field, **kwargs):
        value = field.data
        if hasattr(field,'_value'):
            value = field._value()
        if not value or value == str(None):
            return self.default(field, **kwargs)
        else:
            if not hasattr(field, '_value'):
                field._value = types.MethodType(lambda self: self.data, field)
            if hasattr(field,'link'):
                value = '<a href="%s">%s</a>'%(field.link, value)
            return HiddenInput()(field, **kwargs)+\
                   HTMLString('<p class="form-control-static">'+value+'</p')

class JSONEditor(object):
    """ For fields that expect a JSON value, make a button that pops up a modal
    editor. """
    def __call__(self, field, **kwargs):
        id = kwargs.setdefault('id', field.id)
        modalid = f"{id}_modal"
        saveid = f"{id}_save"
        errid = f"{id}_err"
        kwargs.setdefault('class','form-control')
        kwargs.setdefault('style', "height:250px;")

        btntype = "btn-warning" if field.data else "btn-default"
        html = f"""
        <div id="{modalid}" class="modal fade" tabindex="-1" role="dialog">
          <div class="modal-dialog" role="document">
            <div class="modal-content">
              <div class="modal-header">
                <button type="button" class="close" data-dismiss="modal" aria-label="Close"><span aria-hidden="true">&times;</span></button>
                <h4 class="modal-title">Edit JSON {field.short_name}</h4>
              </div>
              <div class="modal-body">
                {TextArea()(field, **kwargs)}
                <p id="{errid}" class="text-danger"></p>
              </div>
              <div class="modal-footer">
                <button type="button" class="btn btn-default" data-dismiss="modal">Close</button>
                <button id="{saveid}" type="button" class="btn btn-primary">Save changes</button>
              </div>
            </div><!-- /.modal-content -->
          </div><!-- /.modal-dialog -->
        </div><!-- /.modal -->
        <a data-toggle="modal" data-target="#{modalid}" class="btn {btntype}">
            <span class="linklike glyphicon glyphicon-wrench"></span>
        </a>
        <script language="javascript">
        $("#{id}").data("validval",'{field._value()}');
        $("#{modalid}").on("hidden.bs.modal",function(){{
            $("#{id}").val($("#{id}").data('validval'));
            $("#{errid}").text("");
        }}).on("show.bs.modal", function(){{
            var validval = $("#{id}").data('validval');
            $("#{id}").val(JSON.stringify(JSON.parse(validval),null,4));
        }});
        $("#{saveid}").on("click", function(){{
            try{{
                var newval = $("#{id}").val();
                if(newval == "") newval = "{{}}";
                newval = JSON.stringify(JSON.parse(newval));
                $("#{id}").data("validval", newval);
                $("#{modalid}").modal("hide");
            }}catch(e){{
                $("#{errid}").text(e);
            }}
        }});
        </script>
        """
        return HTMLString(html)
