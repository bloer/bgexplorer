"""
@file widgets.py
@author: bloer

Defines a few custom widgets for rendering dynamic elements

"""

#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
import json
from collections import namedtuple

from wtforms.widgets import html_params, HTMLString, HiddenInput, TextInput
from wtforms.utils import unset_value

class TableRow(object):
    """Render a FormField as a row in a table"""
    def __call__(self, field, **kwargs):
        html = []
        kwargs.setdefault('id', field.id)
        html.append("<tr %s>"%html_params(**kwargs))
        for subfield in field:
            html.append("<td>%s</td>"%subfield(**kwargs.get('render_kw',{})))
        #add remove button
        html.append('<td><a onclick="$(this).parents(\'tr\')'
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
            name=field.short_name+'-_INDEX_',
            id=field.id+'-_INDEX_')
        boundform.process(None, unset_value)
        
        #now make the table
        #Flask_Bootstrap wants to give this form-control class...
        kwargs['class'] = kwargs.get('class','').replace('form-control','')
        kwargs['class'] += ' '+kwargs.get('_class','')
        html.append("<table %s>"%html_params(**kwargs));
        html.append("<thead><tr>")
        #should inherit from FieldList...
        for subfield in boundform:
            html.append("<th title='%s'>%s</th>"%(subfield.description,
                                                  subfield.label))
        #one more to hold the remove button
        html.append("<th></th>");
        html.append("</tr></thead>")
        print(boundform.name)
        #now loop through the subforms
        html.append('<tbody class="sortable">')
        for entry in field:
            html.append(TableRow()(entry))
            
        #make a fake hidden form for cloning
        html.append(TableRow()(boundform, render_kw={'disabled':'disabled'},
                               **{'class':'hide template'}))
        html.append("</tbody></table>")
        #add an 'add new' button
        html.append('<button type="button" class="btn text-primary" ')
        html.append('onclick="addrow(\'#%s\')" >'%id)
        html.append('<span class="glyphicon glyphicon-plus"></span>')
        html.append(' Add')
        html.append('</button>')
        html.append(
        """<script type="text/javascript">
            function addrow(obj){
                var row = $(obj).find("tr.template").clone()
                    .removeClass('hide').removeClass('template');
                var index = $(obj).find("tbody tr").size();
                row.attr('id', row.attr('id').replace('_INDEX_',index));
                var inputs = row.find("input").attr("disabled",false);
                inputs.each(function(){
                  $(this).attr('id',$(this).attr('id').replace('_INDEX_',index))
                    .attr('name',$(this).attr('name').replace('_INDEX_',index));
                });
                $(obj).children('tbody').append(row);
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
        html.append('<button class="btn dropdown-toggle" type="button" '
                    '>')
        html.append('<span class="caret"></span></button></div></div>')
        html.append('<ul class="dropdown-menu">')
        for choice in self.choices:
            html.append('<li><a href="javascript:void();" onclick='
                        '"$(\'#%s\').val($(this).text());">'
                        '%s</a></li>'%(kwargs.get('id',field.id),choice))
        html.append('</ul></div></div>')
        return HTMLString(''.join(html))
