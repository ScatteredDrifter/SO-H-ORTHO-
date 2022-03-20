# Copyright (c) 2022 Steven Karrmann
# SPDX-License-Identifier: MIT

# Horizon Board Producer Plugin Usage:
# 1. Copy this Python file (or create a symbolic link) in the KiCad plugins directory
#     * See: https://dev-docs.kicad.org/en/python/pcbnew/#_typical_plugin_structure
# 2. Open KiCad Pcbnew, and open the main board .kicad_pcb file
# 3. In Pcbnew, click "Tools > External Plugins > Horizon Board Producer"
# 4. If successful, 3 gerber zip files are created in the gerbers folder: main board, top plate, and bottom plate

import pcbnew, os, shutil, re

class HorizonBoardProducerPlugin(pcbnew.ActionPlugin):
  def defaults(self):
    self.name = "Horizon Board Producer Rev3.0"
    self.category = "Gerbers, plates, generator"
    self.description = "Generates top plate and bottom plate PCBs, and then creates gerber files for the main, top plate, and bottom plate PCBs"

  def Run(self):
    HorizonBoardProducerPlugin.produce()

  @staticmethod
  def __create_gerbers(board, path):
    """
    Creates Gerber files for a KiCad board and outputs them to the specified path.

    Args:
        board (pcbnew.BOARD): The board for which to generate Gerber files.
        path (str): File system path where Gerber files will be created.
    """
    plot_controller = pcbnew.PLOT_CONTROLLER(board)
    plot_options = plot_controller.GetPlotOptions()
    
    # Set General Options:
    plot_options.SetOutputDirectory(path)

    plot_options.SetPlotFrameRef(False) # "plot border and title block"
    plot_options.SetPlotValue(True)
    plot_options.SetPlotReference(True)
    plot_options.SetPlotInvisibleText(False)
    plot_options.SetExcludeEdgeLayer(True)
    plot_options.SetSketchPadsOnFabLayers(False)
    plot_options.SetPlotViaOnMaskLayer(False) # "do not tent vias"
    
    plot_options.SetDrillMarksType(pcbnew.PCB_PLOT_PARAMS.NO_DRILL_SHAPE)
    plot_options.SetScale(1.0)
    plot_options.SetPlotMode(1) # Filled
    plot_options.SetUseAuxOrigin(False)
    plot_options.SetMirror(False)
    plot_options.SetNegative(False)
    # Note: "check zone fills before plotting" does not seem to be available in API
    
    plot_options.SetUseGerberProtelExtensions(True)
    plot_options.SetCreateGerberJobFile(False)
    plot_options.SetSubtractMaskFromSilk(True)
    plot_options.SetGerberPrecision(6) # "coordinate format: 4.6, unit mm"
    plot_options.SetUseGerberX2format(False)
    plot_options.SetIncludeGerberNetlistInfo(False)
      
    layers = [
      ( 'F.Cu', pcbnew.F_Cu, 'Front Copper' ),
      ( 'B.Cu', pcbnew.B_Cu, 'Back Copper' ),
      ( 'F.SilkS', pcbnew.F_SilkS, 'Front SilkScreen' ),
      ( 'B.SilkS', pcbnew.B_SilkS, 'Back SilkScreen' ),
      ( 'F.Mask', pcbnew.F_Mask, 'Front Mask' ),
      ( 'B.Mask', pcbnew.B_Mask, 'Back Mask' ),
      ( 'Edge.Cuts', pcbnew.Edge_Cuts, 'Edges' )
    ]
      
    for layer in layers:
      plot_controller.SetLayer(layer[1])
      plot_controller.OpenPlotfile(layer[0], pcbnew.PLOT_FORMAT_GERBER, layer[2])
      plot_controller.PlotLayer()
      
    plot_controller.ClosePlot()

  @staticmethod
  def __create_drill_file(board, path):
    """
    Creates drill files for a KiCad board and outputs them to the specified path.

    Args:
        board (pcbnew.BOARD): The board for which to generate Gerber files.
        path (str): File system path where drill files will be created.
    """
    format = {
      'metric': True,
      'zero_format': pcbnew.GENDRILL_WRITER_BASE.DECIMAL_FORMAT,
      'left_digits': 3,
      'right_digits': 3
    }

    options = {
      'mirror_y_axis': False,
      'minimal_header': False,
      'offset': pcbnew.wxPoint(0,0),
      'pth_npth_single_file': False
    }

    drill_writer = pcbnew.EXCELLON_WRITER(board)
    drill_writer.SetFormat(format['metric'], format['zero_format'], format['left_digits'], format['right_digits'])
    drill_writer.SetOptions(options['mirror_y_axis'], options['minimal_header'], options['offset'], options['pth_npth_single_file'])
    drill_writer.SetRouteModeForOvalHoles(False) # JLCPCB requests (Oval Holes Drill Mode -> use alternate drill mode https://support.jlcpcb.com/article/149-how-to-generate-gerber-and-drill-files-in-kicad)
    drill_writer.CreateDrillandMapFilesSet(path, True, False)

  @staticmethod
  def __create_zip(zip_file_path, source_folder):
    """
    Creates a zip file containing all files in the source folder.

    Args:
        zip_file_path (str): The full path and file name for the new zip file.
        source_folder (str): The source folder containing the files to include in the zip.
    """
    shutil.make_archive(zip_file_path, 'zip', source_folder)

  @staticmethod
  def __create_plate_pcb_from_layer(board, layer_name, output_folder, plate_file_name_suffix):
    """
    Creates a new cutout plate PCB, using layer data from the specified source board.
    All tracks and zones are removed from the plate, and only the footprint's cutouts are retained.
    These items within the bounds of the plate's cutout will be preserved:
       * Silkscreen directly on the board (but not in footprints)
       * LOGO footprints (silkscreen images)
       * H footprints (mounting holes)

    Args:
        board (pcbnew.BOARD): The source board
        layer_name (str): The layer name which represents the edge cutouts for the plate.
        output_folder (str): The folder to save the plate .kicad_pcb file.
        plate_file_name_suffix (str): The name appended to the end of the plate .kicad_pcb file name.

    Returns:
        [pcbnew.BOARD]: The plate PCB if created, otherwise None.
    """
    # Create plate PCB file as a copy of the main board
    (_, board_filename) = os.path.split(board.GetFileName())
    plate_file_path = os.path.join(output_folder, board_filename.replace('.kicad_pcb', '-' + plate_file_name_suffix + '.kicad_pcb'))
    plate_pcb = pcbnew.NewBoard(plate_file_path)

    # Copy target layer graphics to edge cuts, and copy silkscreen text
    for drawing in board.GetDrawings():
      new_drawing = drawing.Duplicate()
      if drawing.IsOnLayer(plate_pcb.GetLayerID(layer_name)) and drawing.GetClass() == 'PCB_SHAPE':
        new_drawing.SetLayer(plate_pcb.GetLayerID('Edge.Cuts'))
        plate_pcb.Add(new_drawing)
      elif (drawing.IsOnLayer(plate_pcb.GetLayerID('F.Silkscreen')) or drawing.IsOnLayer(plate_pcb.GetLayerID('B.Silkscreen'))) and drawing.GetClass() == 'PTEXT':
        plate_pcb.Add(new_drawing)

    platebounds = plate_pcb.GetBoardEdgesBoundingBox()

    # If plate has no bounds, then exit
    if platebounds.GetArea() == 0:
      return None

    # Convert footprints to NPTH pads and edge cuts
    for footprint in board.GetFootprints():
      if footprint.GetBoundingBox().Intersects(platebounds):
        new_footprint = pcbnew.FOOTPRINT(footprint)
        new_footprint.SetPosition(footprint.GetPosition())
        if re.match(r'^(H|LOGO)\d+$', footprint.GetReference()): # Preserve pads on 'H' (mounting hole) and 'LOGO' (graphics) footprints
          plate_pcb.Add(new_footprint)
        else:
          remove_footprint_items = []
          for pad in new_footprint.Pads(): # Convert SMD circle/oval pads on target layer to NPTH pads, and remove all other pads
            if pad.IsOnLayer(plate_pcb.GetLayerID(layer_name)) and pad.GetShape() in [pcbnew.PAD_SHAPE_CIRCLE, pcbnew.PAD_SHAPE_OVAL]:
              drill_shape = pcbnew.PAD_DRILL_SHAPE_CIRCLE if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE else pcbnew.PAD_DRILL_SHAPE_OBLONG
              pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
              pad.SetDrillShape(drill_shape)
              pad.SetDrillSize(pad.GetSize())
              pad.SetLayerSet(pad.UnplatedHoleMask())
              pad.SetPosition(pad.GetPosition())
            else:
              remove_footprint_items.append(pad)
          for graphic in new_footprint.GraphicalItems(): # Convert graphics on target layer to edge cuts, and remove all other graphics
            if graphic.IsOnLayer(plate_pcb.GetLayerID(layer_name)):
              graphic.SetLayer(plate_pcb.GetLayerID('Edge.Cuts')) # Move target layer graphics to edge cuts
            else:
              remove_footprint_items.append(graphic)
          for remove_footprint_item in remove_footprint_items:
            new_footprint.Remove(remove_footprint_item)
          if len(new_footprint.Pads()) > 0 or len (new_footprint.GraphicalItems()) > 0:
            plate_pcb.Add(new_footprint)

    plate_pcb.SetFileName(plate_file_path)
    plate_pcb.Save(plate_file_path)
    return plate_pcb

  @staticmethod
  def produce():
    """
    Executes the board production on the currently-opened board.
    """
    board = pcbnew.LoadBoard(pcbnew.GetBoard().GetFileName())

    relative_output_path = '../../gerbers'
    relative_temp_path = '../../temp'
    (board_folder, board_filename) = os.path.split(board.GetFileName())
    temp_path = os.path.normpath(os.path.join(board_folder, relative_temp_path))
    output_path = os.path.normpath(os.path.join(board_folder, relative_output_path))

    if os.path.exists(temp_path):
      shutil.rmtree(temp_path)

    os.makedirs(temp_path)

    if not os.path.exists(output_path):
      os.makedirs(output_path)

    bottom_plate = HorizonBoardProducerPlugin.__create_plate_pcb_from_layer(board, 'B.Adhesive', temp_path, 'bottom-plate')
    top_plate = HorizonBoardProducerPlugin.__create_plate_pcb_from_layer(board, 'F.Adhesive', temp_path, 'top-plate')

    for pcb in [p for p in [board, bottom_plate, top_plate] if p]:
      (board_folder, board_filename) = os.path.split(pcb.GetFileName())
      (board_name, _) = os.path.splitext(board_filename)
      gerber_output_path = os.path.join(temp_path, board_name)
      archive_file_path = os.path.join(output_path, board_name)
      HorizonBoardProducerPlugin.__create_gerbers(pcb, gerber_output_path)
      HorizonBoardProducerPlugin.__create_drill_file(pcb, gerber_output_path)
      HorizonBoardProducerPlugin.__create_zip(archive_file_path, gerber_output_path)

HorizonBoardProducerPlugin().register()