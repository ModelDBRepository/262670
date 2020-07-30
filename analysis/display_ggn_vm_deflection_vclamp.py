# display_ggn_vm_deflection_vclamp.py --- 
# Author: Subhasis  Ray
# Created: Thu Sep  6 10:51:07 EDT 2018
# Last-Updated: Tue Jan  8 18:12:58 2019 (-0500)
#           By: Subhasis Ray
# Version: $Id$

# Code:
"""Show in 3D the deflection of GGN Vm from data generated by script
`ggn_voltage_attenuation_vclamp.py`

This should work for an hdf5 data file where the /celltemplate dataset
has the GGN celltemplate file content and the voltage traces are
stored in v_{nodename} datasets. The voltage datasets should have
`section` attribute set to the original section from which it was
recorded so that we can map back to the section in 3D view.

"""

from __future__ import print_function
import sys
if sys.platform == 'win32':
    sys.path += ['D:/subhasis_ggn/model/analysis', 'D:/subhasis_ggn/model/nrn',
                 'D:/subhasis_ggn/model/morphutils', 'D:/subhasis_ggn/model/mb',
                 'D:/subhasis_ggn/model/mb/network']
else:
    sys.path += ['/home/rays3/projects/ggn/analysis',
                 '/home/rays3/projects/ggn/morphutils',
                 '/home/rays3/projects/ggn/nrn']
import os
import argparse
import h5py as h5
import numpy as np
import random
from matplotlib import pyplot as plt
import colorcet as cc
import yaml
import pint
from collections import defaultdict
import pandas as pd
import network_data_analysis as nda
from matplotlib.backends.backend_pdf import PdfPages
import pn_kc_ggn_plot_mpl as myplot
import neurograph as ng
import nrnutils as nu
import timeit
from neuron import h
import vtk
from sklearn import cluster, preprocessing
import morph3d
from vtk.util import numpy_support as vtknp
import show_animated_data_ctf as danim

plt.style.use('dark_background')

plt.rc('lines', linewidth=2.0)
plt.style.use('dark_background')

def make_color_table():
    ctf = vtk.vtkColorTransferFunction()
    # ctf.SetColorSpaceToDiverging()
    ctf.AddRGBPoint(-55.0, 1, 1, 1)
    ctf.AddRGBPoint(-51.0, 1, 1, 1)
    ctf.AddRGBPoint(-25.0, 1, 1, 1)
    return ctf


def make_ctf_from_linear_segmented_cm(vmin, vmax, cm=cc.m_bgy):
    ctf = vtk.vtkColorTransferFunction()
    vrange = np.linspace(vmin, vmax, cm.N)
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cm)
    for val in vrange:
        r, g, b, a = sm.to_rgba(val)
        ctf.AddRGBPoint(val, r, g, b)
    return ctf


def get_sec_pos(sec_name_list, name_sec_map):
    pos = []
    for name in sec_name_list:
        sec = name_sec_map[name]
        sec.push()
        pos.append((h.x3d(0.5), h.y3d(0.5), h.z3d(0.5)))
        h.pop_section()
    return np.array(pos)


def make_vm_spheres(pos, vm, ctf, radius=10):
    colors = vtknp.numpy_to_vtk(vm, deep=True,
                                array_type=vtk.VTK_DOUBLE)
    colors.SetName('VmColors')
    sphere = vtk.vtkSphereSource()
    sphere.SetPhiResolution(10)
    sphere.SetThetaResolution(10)
    sphere.SetRadius(radius)
    sphereglyph = vtk.vtkGlyph3D()
    sphereglyph.SetScaleModeToDataScalingOff()
    sphereglyph.SetSourceConnection(sphere.GetOutputPort())
    # spheremapper = vtk.vtkPolyDataMapper()
    # spheremapper.SetInputConnection(sphereglyph.GetOutputPort())
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(len(pos))
    for ii, p in enumerate(pos):
        points.SetPoint(ii, p)
    spherepoly = vtk.vtkPolyData()
    spherepoly.SetPoints(points)
    spherepoly.GetPointData().SetScalars(colors)
    sphereglyph.SetInputData(spherepoly)
    
    # spheremapper.ScalarVisibilityOn()
    # spheremapper.SelectColorArray('VmColors')
    # spheremapper.SetLookupTable(vm_ctf)
    # sphereactor = vtk.vtkActor()
    # sphereactor.SetMapper(spheremapper)
    return {'source': sphere,
            'glyph': sphereglyph,
            'polydata': spherepoly,
    }


def get_ggn(fname):
    with h5.File(fname, 'r') as fd:
        ggn_model = fd['/celltemplate'].value.decode('utf-8')
        cellname = [line for line in ggn_model.split('\n')
                    if 'begintemplate' in line]
        rest = cellname[0].partition('begintemplate')[-1]
        cellname = rest.split()[0]
        if not hasattr(h, cellname):
            h(ggn_model)
        return eval('h.{}()'.format(cellname))


def show_peak_vm_ggn(fname, rot=None, drot=None, pos=None,
                     frames=0, framerate=24, moviefile=None, bg=(0, 0, 0), radius=10, lw=10, width=320, height=240):
    """Display the GGN morphology with color coded Vm"""
    sec_delv = {}
    with h5.File(fname, 'r') as fd:
        for node in fd:
            if node.startswith('v_'):
                v = fd[node].value
                delv = max(v) - v[0]
                sec = str(fd[node].attrs['section'])
                sec_delv[sec] = delv
    print('Computed delV')
    ggn = get_ggn(fname)
    graph = nu.nrngraph(ggn)
    soma = [graph.node[node] for node in graph if node.endswith('soma')]
    soma = soma[0]
    name_sec_map = {}
    for secname in sec_delv:
        name_sec_map[secname] = graph.nodes[secname]['orig']
    secpos = get_sec_pos(sec_delv.keys(), name_sec_map)
    if pos is None:
        pos = [(secpos[:, 0].min() + secpos[:, 0].max()) / 2.0,
               (secpos[:, 1].min() + secpos[:, 1].max()) / 2.0,
               (secpos[:, 2].min() + secpos[:, 2].max()) / 2.0]

    # This helps to prevent the neuron from rotating outside camera view
    soma  = {'x': pos[0], 'y': pos[1], 'z': pos[2]}
    print('Origin moved to', pos)
    nodecolor = {ii: [(255 - bc) for bc in bg] for ii in range(10)}
    polydata = morph3d.nrngraph2polydata(graph, nodecolor=nodecolor,  #ng.nodecolor_7q,
                                         lines=1.0)
    ggn3d = polydata # morph3d.get_cylinder_view(polydata) <- with get_cylinder_view SetLineWidth does not have any effect
    # Rotation is always with soma as origin
    transfilter, transform = morph3d.get_transformed(ggn3d, soma, pos, rot, relative=True)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(transfilter.GetOutputPort())
    mapper.ScalarVisibilityOn()
    mapper.SetScalarModeToUseCellFieldData()
    mapper.SelectColorArray('Colors')    
    # This helps to prevent the neuron from rotating outside camera view
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetOpacity(0.2)
    actor.GetProperty().SetLineWidth(lw)
    actor.SetOrigin(pos)
    vm_deflection = sec_delv.values()
    print(min(vm_deflection), max(vm_deflection))
    # vm_ctf = make_viridis_ctf(10.0, 30.0)
    vm_ctf = make_ctf_from_linear_segmented_cm(int(min(vm_deflection)), int(0.5 + max(vm_deflection)), cc.m_isolum)   # min and max give not-so-round numbers
    vm_disp = make_vm_spheres(secpos, vm_deflection, vm_ctf, radius=radius)
    vmxfilt, vmx = morph3d.get_transformed(vm_disp['glyph'], soma,
                                           pos, rot, relative=True)
    vmxfilt.Update()
    vm_mapper = vtk.vtkPolyDataMapper()
    vm_mapper.SelectColorArray('VmColors')
    vm_mapper.SetScalarModeToUsePointFieldData()
    vm_mapper.SetInputConnection(vmxfilt.GetOutputPort())
    # vm_mapper.ScalarVisibilityOn()
    vm_mapper.SetLookupTable(vm_ctf)    
    vm_actor = vtk.vtkActor()
    vm_actor.SetMapper(vm_mapper)
    # This helps to prevent the neuron from rotating outside camera view
    vm_actor.SetOrigin(pos)

    colorbar = vtk.vtkScalarBarActor()
    colorbar.SetLookupTable(vm_ctf)    
    colorbar.SetTitle('dVm (mV)')
    colorbar.SetNumberOfLabels(5)
    colorbar.SetWidth(0.1)
    colorbar.SetHeight(0.7)
    colorbar.SetPosition(0.9, 0.1)
    colorbar.SetAnnotationTextScaling(True)
    textcolor = [1 - bg[0], 1 - bg[1], 1 - bg[2]]
    colorbar.GetTitleTextProperty().SetFontFamilyToArial()
    colorbar.GetTitleTextProperty().SetFontSize(12)
    colorbar.GetTitleTextProperty().SetColor(*textcolor)
    colorbar.GetTitleTextProperty().SetShadow(False)
    colorbar.GetTitleTextProperty().ItalicOff()
    colorbar.GetLabelTextProperty().SetFontFamilyToArial()
    colorbar.GetLabelTextProperty().SetFontSize(10)
    colorbar.GetLabelTextProperty().SetJustificationToCentered()
    colorbar.GetLabelTextProperty().SetColor(*textcolor)
    colorbar.GetLabelTextProperty().SetShadow(False)
    colorbar.GetLabelTextProperty().ItalicOff()
    
    renderer = vtk.vtkRenderer()
    renderer.AddActor(actor)
    renderer.AddActor(vm_actor)
    renderer.AddActor2D(colorbar)
    renderer.SetBackground(*bg)
    # camera = vtk.vtkCamera()
    # # This was found experimentally
    # camera.SetPosition((-323.62152099609375, +398.5799446105957, 1000.250453948881))
    # camera.SetFocalPoint(pos)
    # renderer.SetActiveCamera(camera)
    # renderer.GetActiveCamera().SetViewAngle(30)
    win = vtk.vtkRenderWindow()
    win.AddRenderer(renderer)
    win.SetSize(width, height)
    win.Render()
    # Strangely, increasing view angle makes the object distance. What is this view angle?
    renderer.GetActiveCamera().SetViewAngle(23)
    # print(renderer.GetActiveCamera().GetPosition())
    # print(renderer.GetActiveCamera().GetFocalPoint())
    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(win)
    interactor.Initialize()
    if moviefile is not None:
        dump_movie([vm_actor, actor], win, drot[0], drot[1], drot[2],
                   frames, framerate, moviefile)
    interactor.Start()

        
def dump_movie(actors, win, dx, dy, dz, frames, framerate, filename):
    windowToImageFilter = vtk.vtkWindowToImageFilter()
    windowToImageFilter.SetInput(win)
    # windowToImageFilter.SetInputBufferTypeToRGBA()
    windowToImageFilter.ReadFrontBufferOff()
    windowToImageFilter.Update()
    writer = vtk.vtkAVIWriter()
    writer.SetQuality(2)
    writer.SetRate(framerate)
    writer.SetInputConnection(windowToImageFilter.GetOutputPort())
    writer.SetFileName(filename)
    writer.Start()
    for frame in range(frames):
        for actor in actors:
            actor.RotateX(dx)
            actor.RotateY(dy)
            actor.RotateZ(dz)
        win.GetInteractor().GetRenderWindow().Render()
        windowToImageFilter.Modified()  # This is crucial
        writer.Write()
    writer.End()


    

if __name__ == '__main__':
    """First arg input data file, second arg background color, if there is a third dump a movie"""
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', dest='fname', help='input data file')
    parser.add_argument('-r', type=float, dest='radius', default=10, help='radius of Vm spheres')
    parser.add_argument('-b', dest='bg', default='0 0 0', help='background color "r g b" in decimal')
    parser.add_argument('-m', dest='dump', default=None, help='if specified dump movie')
    parser.add_argument('-l', type=float, dest='lw', default=10, help='line width for neurites')
    parser.add_argument('-s', type=str, dest='resolution', default='1024x768', help='frame resolution in pixels {width}x{height}')
    args = parser.parse_args()
    resolution =  args.resolution.split('x')
    width =  int(resolution[0].strip())
    height = int(resolution[1].strip())
    bg = [int(ii) for ii in args.bg.split()]
    moviefile = args.dump
    x = show_peak_vm_ggn(args.fname, rot=[('x', 0), ('y', 0), ('z', -90)], pos=None,
                         drot=[0, 0.5, 0], frames=360,
                         moviefile=moviefile, bg=bg, radius=args.radius, lw=args.lw, width=width, height=height)


# 
# display_ggn_vm_deflection_vclamp.py ends here