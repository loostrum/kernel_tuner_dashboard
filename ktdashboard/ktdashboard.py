#!/usr/bin/env python
import json
import sys
import os
import argparse

import panel as pn
import panel.widgets as pnw
import pandas as pd
from bokeh.models import HoverTool, LinearColorMapper
from bokeh.plotting import ColumnDataSource, figure


class KTdashboard:
    """ Main object to instantiate to hold everything related to a running dashboard"""

    def __init__(self, cache_file, demo=False):
        self.demo = demo
        self.cache_file = cache_file
        self.cache_file_handle = None

        # read in the cachefile, retry until file is non-empty
        self.cache_file_handle = open(cache_file, "r")
        filestr = ""
        data = []
        while not data:
            self.cache_file_handle.seek(0)
            filestr = self.cache_file_handle.read().strip()
            while not filestr:
                self.cache_file_handle.seek(0)
                filestr = self.cache_file_handle.read().strip()

            # if file was not properly closed, pretend it was properly closed
            if not filestr[-3:] == "}\n}":
                # remove the trailing comma if any, and append closing brackets
                if filestr[-1] == ",":
                    filestr = filestr[:-1]
                filestr = filestr + "}\n}"

            cached_data = json.loads(filestr)
            self.kernel_name = cached_data["kernel_name"]
            self.device_name = cached_data["device_name"]
            if "objective" in cached_data:
                self.objective = cached_data["objective"]
            else:
                self.objective = "time"

            # get the performance data
            data = list(cached_data["cache"].values())
            data = [d for d in data if d[self.objective] != 1e20 and not isinstance(d[self.objective], str)]

        # use all data or just the first 1000 records in demo mode
        self.index = len(data)
        if self.demo:
            self.index = min(len(data), 1000)

        # figure out which keys are interesting
        single_value_tune_param_keys = [key for key in cached_data["tune_params_keys"] if len(cached_data["tune_params"][key]) == 1]
        tune_param_keys = [key for key in cached_data["tune_params_keys"] if key not in single_value_tune_param_keys]
        single_value_keys = [key for key in data[0].keys() if not isinstance(data[0][key],list) and key not in single_value_tune_param_keys]
        output_keys = [key for key in single_value_keys if key not in tune_param_keys]
        float_keys = [key for key in output_keys if isinstance(data[0][key], float)]

        self.single_value_tune_param_keys = single_value_tune_param_keys
        self.tune_param_keys = tune_param_keys
        self.single_value_keys = single_value_keys
        self.output_keys = output_keys
        self.float_keys = float_keys

        self.data_df = pd.DataFrame(data[:self.index])[single_value_keys]
        self.source = ColumnDataSource(data=self.data_df)
        self.data = data

        plot_options=dict(height=500, width=900)
        plot_options['tools'] = [HoverTool(tooltips=[(k, "@{"+k+"}" + ("{0.00}" if k in float_keys else "")) for k in single_value_keys]), "box_select,box_zoom,save,reset"]

        self.plot_options = plot_options

        # find default key
        default_key = 'GFLOP/s'
        if default_key not in single_value_keys:
            default_key = 'time'  # Check if time is defined
            if default_key not in single_value_keys:
                default_key = single_Value_keys[0]

        # setup widgets
        #self.yvariable = pnw.Select(name='Y', value=default_key, options=single_value_keys)
        #self.xvariable = pnw.Select(name='X', value='index', options=['index']+single_value_keys)
        #self.colorvariable = pnw.Select(name='Color By', value=default_key, options=single_value_keys)
        self.yvariable = pnw.Select(name='Y', value='GB/s', options=single_value_keys)
        self.xvariable = pnw.Select(name='X', value='GB/s/W (system)', options=['index']+single_value_keys)
        self.colorvariable = pnw.Select(name='Color By', value='GPU frequency (MHz)', options=single_value_keys)

        # connect widgets with the function that draws the scatter plot
        self.scatter = pn.bind(self.make_scatter, xvariable=self.xvariable, yvariable=self.yvariable, color_by=self.colorvariable)

        # actually build up the dashboard
        self.dashboard = pn.template.BootstrapTemplate(title='Kernel Tuner Dashboard')
        self.dashboard.sidebar.append(pn.Column(self.yvariable, self.xvariable, self.colorvariable))
        self.dashboard.main.append(self.scatter)

    def __del__(self):
        if self.cache_file_handle is not None:
            self.cache_file_handle.close()

    def notebook(self):
        """ Return a static version of the dashboard without the template """
        return pn.Row(pn.Column(self.yvariable, self.xvariable, self.colorvariable), self.scatter)

    def update_colors(self, color_by):
        color_mapper = LinearColorMapper(palette='Viridis256', low=min(self.data_df[color_by]),
                                         high=max(self.data_df[color_by]))
        color = {'field': color_by, 'transform': color_mapper}
        return color

    def make_scatter(self, xvariable, yvariable, color_by):
        color = self.update_colors(color_by)

        x = xvariable
        y = yvariable

        f = figure(**self.plot_options)
        f.scatter(x, y, size=12, color=color, alpha=0.5, source=self.source)
        f.xaxis.axis_label = x
        f.yaxis.axis_label = y

        pane = pn.Column(pn.pane.Markdown(f"## Auto-tuning {self.kernel_name} on {self.device_name}"), pn.pane.Bokeh(f))

        return pane

    def update_plot(self, i):
        stream_dict = {k:[v] for k,v in dict(self.data[i], index=i).items() if k in ['index']+self.single_value_keys}
        self.source.stream(stream_dict)

    def update_data(self):
        if not self.demo:
            new_contents = self.cache_file_handle.read().strip()
            if new_contents:

                # process new contents (parse as JSON, make into dict that goes into source.stream)
                new_contents_json = "{" + new_contents[:-1] + "}"
                new_data = list(json.loads(new_contents_json).values())

                for i,element in enumerate(new_data):

                    stream_dict = {k:[v] for k,v in dict(element, index=self.index+i).items() if k in ['index']+self.single_value_keys}
                    self.source.stream(stream_dict)

                self.index += len(new_data)

        if self.demo:
            if self.index < (len(self.data)-1):
                self.update_plot(self.index)
                self.index += 1


def cli():
    """ implements the command-line interface to start the dashboard """


    parser = argparse.ArgumentParser()
    parser.add_argument("--file", "-f", help="Path to cache file", required=True)
    parser.add_argument("--demo", action="store_true", help="Enable demo mode that mimicks runnign a Kernel Tuner session")
    parser.add_argument("--port", "-p", type=int, default=40000, help="Dashboard port (default: %(default)s")

    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print("Cachefile not found")
        exit(1)

    db = KTdashboard(args.file, demo=args.demo)

    db.dashboard.servable()

    def dashboard_f():
        """ wrapper function to add the callback, doesn't work without this construct """
        pn.state.add_periodic_callback(db.update_data, 1000)
        return db.dashboard
    server = pn.serve(dashboard_f, port=args.port, websocket_origin='*', show=False)



if __name__ == "__main__":
    cli()
