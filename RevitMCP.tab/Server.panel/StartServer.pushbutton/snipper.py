# -*- coding: utf-8 -*-
"""
Revit MCP Visual Context Snipper & Annotation Tool.
Allows users to snip any screen area in Revit, add freehand/arrow/box drawings,
and automatically save the annotated image into the MCP cache for AI agents.
"""

import sys
import os
import time
import json
import math
import datetime
import traceback
import tempfile
import shutil

import clr
clr.AddReference("System.Drawing")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System.Drawing import Bitmap, Graphics, Size, Point, Rectangle as DrawingRectangle
from System.Drawing.Imaging import ImageFormat
from System.Windows.Forms import Screen
import System

from System.Windows import (
    Window, WindowStyle, WindowState, Application, Point as WpfPoint,
    Rect, Size as WpfSize, Thickness, Visibility, HorizontalAlignment, VerticalAlignment,
    UIElement, WindowStartupLocation, ResizeMode, MessageBox, CornerRadius, GridLength, GridUnitType,
    FontWeights
)
from System.Windows.Controls import (
    Canvas, Border, StackPanel, Button, TextBlock, Image, Grid,
    RowDefinition, ColumnDefinition, InkCanvas, InkCanvasEditingMode, Orientation
)
from System.Windows.Media import (
    SolidColorBrush, Color, Colors, ImageBrush, Stretch, Pen as WpfPen, DoubleCollection, PixelFormats,
    CombinedGeometry, GeometryCombineMode, RectangleGeometry
)
from System.Windows.Media.Imaging import (
    RenderTargetBitmap, BitmapSource, BitmapImage, PngBitmapEncoder, BitmapFrame, BitmapCacheOption
)
from System.Windows.Ink import DrawingAttributes, Stroke
from System.Windows.Input import (
    KeyEventArgs, Key, MouseButton, Cursors, MouseButtonState, StylusPoint, StylusPointCollection
)
from System.Windows.Shapes import Rectangle as WpfRectShape, Path as WpfPath, Line as WpfLine

DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".revit_mcp")
SAVE_DIR = os.environ.get("REVIT_MCP_CACHE_DIR", DEFAULT_CACHE_DIR)
LATEST_PNG = os.path.join(SAVE_DIR, "latest_screenshot.png")
LATEST_JSON = os.path.join(SAVE_DIR, "latest_screenshot.json")
USER_SNIP_PNG = os.path.join(SAVE_DIR, "latest_user_snip.png")
USER_SNIP_JSON = os.path.join(SAVE_DIR, "latest_user_snip.json")
SCREENSHOTS_DIR = os.path.join(SAVE_DIR, "screenshots")

# Simple distinct colors palette
DRAWING_COLORS = [
    ("#E74C3C", "Red"),
    ("#2ECC71", "Green"),
    ("#3498DB", "Blue"),
    ("#F1C40F", "Yellow"),
    ("#E67E22", "Orange"),
    ("#FFFFFF", "White"),
]


def capture_all_screens():
    """Captures the entire virtual desktop spanning all monitors into a System.Drawing.Bitmap."""
    screens = Screen.AllScreens
    min_x = min([s.Bounds.X for s in screens])
    min_y = min([s.Bounds.Y for s in screens])
    max_x = max([s.Bounds.Right for s in screens])
    max_y = max([s.Bounds.Bottom for s in screens])
    
    width = max_x - min_x
    height = max_y - min_y
    
    bmp = Bitmap(width, height)
    g = Graphics.FromImage(bmp)
    g.CopyFromScreen(min_x, min_y, 0, 0, Size(width, height))
    g.Dispose()
    
    return bmp, min_x, min_y, width, height


def bitmap_to_bitmap_source(bmp):
    """Converts a System.Drawing.Bitmap to WPF BitmapSource using memory stream."""
    import System.IO
    ms = System.IO.MemoryStream()
    bmp.Save(ms, ImageFormat.Png)
    ms.Position = 0
    
    bs = BitmapImage()
    bs.BeginInit()
    bs.StreamSource = ms
    bs.CacheOption = BitmapCacheOption.OnLoad
    bs.EndInit()
    bs.Freeze()
    return bs


class AnnotationWindow(Window):
    """Interactive markup window with arrow, box, and pen tools."""
    def __init__(self, cropped_bmp, on_saved_callback=None):
        super(AnnotationWindow, self).__init__()
        self.cropped_bmp = cropped_bmp
        self.on_saved_callback = on_saved_callback
        
        self.current_tool = "pen"  # "pen", "arrow", "rect", "eraser"
        self.current_color = Color.FromRgb(231, 76, 60) # Red default
        self.current_thickness = 4.0
        
        self.shape_start = None
        self.temp_stroke = None
        
        self.Title = "Revit MCP Markup & Snip"
        self.WindowStyle = getattr(WindowStyle, "None")
        self.AllowsTransparency = True
        self.Background = SolidColorBrush(Color.FromRgb(24, 24, 31))
        self.Topmost = True
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.ResizeMode = ResizeMode.NoResize
        
        self.init_ui()

    def init_ui(self):
        self.image_source = bitmap_to_bitmap_source(self.cropped_bmp)
        img_w = float(self.cropped_bmp.Width)
        img_h = float(self.cropped_bmp.Height)
        
        max_w = min(1400.0, float(Screen.PrimaryScreen.WorkingArea.Width) - 100.0)
        max_h = min(850.0, float(Screen.PrimaryScreen.WorkingArea.Height) - 160.0)
        
        scale = min(1.0, max_w / max(1.0, img_w), max_h / max(1.0, img_h))
        display_w = img_w * scale
        display_h = img_h * scale
        
        self.Width = max(display_w + 32.0, 540.0)
        self.Height = display_h + 125.0
        
        root_border = Border()
        root_border.Margin = Thickness(8)
        root_border.Background = SolidColorBrush(Color.FromRgb(24, 24, 31))
        root_border.CornerRadius = CornerRadius(10)
        root_border.BorderBrush = SolidColorBrush(Color.FromRgb(47, 47, 61))
        root_border.BorderThickness = Thickness(1)
        
        main_grid = Grid()
        main_grid.Margin = Thickness(10)
        
        r0 = RowDefinition()
        r0.Height = GridLength.Auto
        r1 = RowDefinition()
        r1.Height = GridLength(1, GridUnitType.Star)
        r2 = RowDefinition()
        r2.Height = GridLength.Auto
        
        main_grid.RowDefinitions.Add(r0)
        main_grid.RowDefinitions.Add(r1)
        main_grid.RowDefinitions.Add(r2)
        
        # --- Top Toolbar ---
        top_bar = Grid()
        c0 = ColumnDefinition()
        c0.Width = GridLength(1, GridUnitType.Star)
        c1 = ColumnDefinition()
        c1.Width = GridLength.Auto
        top_bar.ColumnDefinitions.Add(c0)
        top_bar.ColumnDefinitions.Add(c1)
        
        tools_panel = StackPanel()
        tools_panel.Orientation = Orientation.Horizontal
        
        title_lbl = TextBlock()
        title_lbl.Text = "✍️ Markup"
        title_lbl.FontWeight = FontWeights.Bold
        title_lbl.Foreground = SolidColorBrush(Color.FromRgb(255, 255, 255))
        title_lbl.VerticalAlignment = VerticalAlignment.Center
        title_lbl.Margin = Thickness(0, 0, 12, 0)
        title_lbl.FontSize = 13
        tools_panel.Children.Add(title_lbl)
        
        # Tool Buttons
        self.btn_pen = self._create_tool_button("✏️ Pen", "pen", is_active=True)
        self.btn_arrow = self._create_tool_button("➡️ Arrow", "arrow")
        self.btn_rect = self._create_tool_button("⬜ Box", "rect")
        self.btn_eraser = self._create_tool_button("🧹 Eraser", "eraser")
        
        tools_panel.Children.Add(self.btn_pen)
        tools_panel.Children.Add(self.btn_arrow)
        tools_panel.Children.Add(self.btn_rect)
        tools_panel.Children.Add(self.btn_eraser)
        
        sep1 = Border()
        sep1.Width = 1
        sep1.Height = 18
        sep1.Background = SolidColorBrush(Color.FromRgb(60, 60, 75))
        sep1.Margin = Thickness(8, 0, 8, 0)
        tools_panel.Children.Add(sep1)
        
        # Colors Palette
        self.color_buttons = []
        for hex_code, desc in DRAWING_COLORS:
            r = int(hex_code[1:3], 16)
            g = int(hex_code[3:5], 16)
            b = int(hex_code[5:7], 16)
            col = Color.FromRgb(r, g, b)
            
            cbtn = Button()
            cbtn.Width = 20
            cbtn.Height = 20
            cbtn.Margin = Thickness(3, 0, 3, 0)
            cbtn.Background = SolidColorBrush(col)
            cbtn.BorderThickness = Thickness(2 if hex_code == "#E74C3C" else 0)
            cbtn.BorderBrush = SolidColorBrush(Color.FromRgb(255, 255, 255))
            cbtn.ToolTip = desc
            cbtn.Cursor = Cursors.Hand
            
            def make_color_handler(target_col, target_btn):
                def handler(s, e):
                    self.current_color = target_col
                    self._update_drawing_attributes()
                    for cb in self.color_buttons:
                        cb.BorderThickness = Thickness(0)
                    target_btn.BorderThickness = Thickness(2)
                return handler
                
            cbtn.Click += make_color_handler(col, cbtn)
            self.color_buttons.append(cbtn)
            tools_panel.Children.Add(cbtn)
            
        Grid.SetColumn(tools_panel, 0)
        top_bar.Children.Add(tools_panel)
        
        close_btn = Button()
        close_btn.Content = "✕"
        close_btn.Width = 24
        close_btn.Height = 24
        close_btn.Background = SolidColorBrush(Colors.Transparent)
        close_btn.Foreground = SolidColorBrush(Color.FromRgb(140, 140, 160))
        close_btn.BorderThickness = Thickness(0)
        close_btn.FontWeight = FontWeights.Bold
        close_btn.Cursor = Cursors.Hand
        close_btn.Click += lambda s, e: self.Close()
        Grid.SetColumn(close_btn, 1)
        top_bar.Children.Add(close_btn)
        
        Grid.SetRow(top_bar, 0)
        main_grid.Children.Add(top_bar)
        
        # --- Center Canvas Area ---
        canvas_border = Border()
        canvas_border.Margin = Thickness(0, 8, 0, 8)
        canvas_border.Background = SolidColorBrush(Color.FromRgb(18, 18, 23))
        canvas_border.CornerRadius = CornerRadius(6)
        canvas_border.ClipToBounds = True
        canvas_border.HorizontalAlignment = HorizontalAlignment.Center
        canvas_border.VerticalAlignment = VerticalAlignment.Center
        
        self.ink_canvas = InkCanvas()
        self.ink_canvas.Width = display_w
        self.ink_canvas.Height = display_h
        
        img_brush = ImageBrush(self.image_source)
        img_brush.Stretch = Stretch.Fill
        self.ink_canvas.Background = img_brush
        
        self._update_drawing_attributes()
        
        self.ink_canvas.MouseDown += self._on_canvas_mouse_down
        self.ink_canvas.MouseMove += self._on_canvas_mouse_move
        self.ink_canvas.MouseUp += self._on_canvas_mouse_up
        
        canvas_border.Child = self.ink_canvas
        Grid.SetRow(canvas_border, 1)
        main_grid.Children.Add(canvas_border)
        
        # --- Bottom Action Bar ---
        bottom_bar = Grid()
        bc0 = ColumnDefinition()
        bc0.Width = GridLength(1, GridUnitType.Star)
        bc1 = ColumnDefinition()
        bc1.Width = GridLength.Auto
        bottom_bar.ColumnDefinitions.Add(bc0)
        bottom_bar.ColumnDefinitions.Add(bc1)
        
        size_lbl = TextBlock()
        size_lbl.Text = "{} × {} px".format(int(img_w), int(img_h))
        size_lbl.Foreground = SolidColorBrush(Color.FromRgb(100, 100, 120))
        size_lbl.FontSize = 11
        size_lbl.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(size_lbl, 0)
        bottom_bar.Children.Add(size_lbl)
        
        action_panel = StackPanel()
        action_panel.Orientation = Orientation.Horizontal
        
        clear_btn = Button()
        clear_btn.Content = "Clear All"
        clear_btn.Background = SolidColorBrush(Color.FromRgb(47, 47, 61))
        clear_btn.Foreground = SolidColorBrush(Color.FromRgb(200, 200, 210))
        clear_btn.BorderThickness = Thickness(0)
        clear_btn.Padding = Thickness(12, 6, 12, 6)
        clear_btn.Margin = Thickness(0, 0, 8, 0)
        clear_btn.Cursor = Cursors.Hand
        clear_btn.Click += self._on_clear_clicked
        action_panel.Children.Add(clear_btn)
        
        send_btn = Button()
        send_btn.Content = "✓ Send to AI"
        send_btn.Background = SolidColorBrush(Color.FromRgb(46, 204, 113)) # Green
        send_btn.Foreground = SolidColorBrush(Color.FromRgb(255, 255, 255))
        send_btn.FontWeight = FontWeights.Bold
        send_btn.BorderThickness = Thickness(0)
        send_btn.Padding = Thickness(16, 6, 16, 6)
        send_btn.Cursor = Cursors.Hand
        send_btn.Click += self._on_send_clicked
        action_panel.Children.Add(send_btn)
        
        Grid.SetColumn(action_panel, 1)
        bottom_bar.Children.Add(action_panel)
        
        Grid.SetRow(bottom_bar, 2)
        main_grid.Children.Add(bottom_bar)
        
        root_border.Child = main_grid
        self.Content = root_border
        
        self.KeyDown += self._on_key_down

    def _create_tool_button(self, label, tool_id, is_active=False):
        btn = Button()
        btn.Content = label
        btn.Height = 26
        btn.Margin = Thickness(0, 0, 6, 0)
        btn.Padding = Thickness(8, 0, 8, 0)
        btn.FontSize = 11
        btn.Cursor = Cursors.Hand
        btn.BorderThickness = Thickness(1)
        
        if is_active:
            btn.Background = SolidColorBrush(Color.FromRgb(52, 73, 94))
            btn.Foreground = SolidColorBrush(Color.FromRgb(255, 255, 255))
            btn.BorderBrush = SolidColorBrush(Color.FromRgb(52, 152, 219))
        else:
            btn.Background = SolidColorBrush(Color.FromRgb(32, 32, 42))
            btn.Foreground = SolidColorBrush(Color.FromRgb(160, 160, 180))
            btn.BorderBrush = SolidColorBrush(Color.FromRgb(47, 47, 61))
            
        def on_click(s, e):
            self.current_tool = tool_id
            for b in [self.btn_pen, self.btn_arrow, self.btn_rect, self.btn_eraser]:
                b.Background = SolidColorBrush(Color.FromRgb(32, 32, 42))
                b.Foreground = SolidColorBrush(Color.FromRgb(160, 160, 180))
                b.BorderBrush = SolidColorBrush(Color.FromRgb(47, 47, 61))
            btn.Background = SolidColorBrush(Color.FromRgb(52, 73, 94))
            btn.Foreground = SolidColorBrush(Color.FromRgb(255, 255, 255))
            btn.BorderBrush = SolidColorBrush(Color.FromRgb(52, 152, 219))
            
            if tool_id == "eraser":
                self.ink_canvas.EditingMode = InkCanvasEditingMode.EraseByStroke
            elif tool_id == "pen":
                self.ink_canvas.EditingMode = InkCanvasEditingMode.Ink
            else:
                self.ink_canvas.EditingMode = getattr(InkCanvasEditingMode, "None")
                
            self._update_drawing_attributes()
            
        btn.Click += on_click
        return btn

    def _update_drawing_attributes(self):
        da = DrawingAttributes()
        da.Color = self.current_color
        da.Width = self.current_thickness
        da.Height = self.current_thickness
        da.FitToCurve = True
        self.ink_canvas.DefaultDrawingAttributes = da

    def _on_canvas_mouse_down(self, sender, e):
        if e.LeftButton == MouseButtonState.Pressed and self.current_tool in ["rect", "arrow"]:
            self.shape_start = e.GetPosition(self.ink_canvas)
            self.temp_stroke = None
            self.ink_canvas.CaptureMouse()

    def _on_canvas_mouse_move(self, sender, e):
        if self.shape_start and e.LeftButton == MouseButtonState.Pressed:
            p2 = e.GetPosition(self.ink_canvas)
            
            # Remove previous transient stroke
            if self.temp_stroke and self.temp_stroke in self.ink_canvas.Strokes:
                self.ink_canvas.Strokes.Remove(self.temp_stroke)
                
            da = DrawingAttributes()
            da.Color = self.current_color
            da.Width = self.current_thickness
            da.Height = self.current_thickness
            
            if self.current_tool == "rect":
                x1 = self.shape_start.X
                y1 = self.shape_start.Y
                x2 = p2.X
                y2 = p2.Y
                
                pts = StylusPointCollection()
                pts.Add(StylusPoint(x1, y1))
                pts.Add(StylusPoint(x2, y1))
                pts.Add(StylusPoint(x2, y2))
                pts.Add(StylusPoint(x1, y2))
                pts.Add(StylusPoint(x1, y1))
                
                self.temp_stroke = Stroke(pts, da)
                self.ink_canvas.Strokes.Add(self.temp_stroke)
                
            elif self.current_tool == "arrow":
                x1 = self.shape_start.X
                y1 = self.shape_start.Y
                x2 = p2.X
                y2 = p2.Y
                
                dx = x2 - x1
                dy = y2 - y1
                dist = math.sqrt(dx * dx + dy * dy)
                
                pts = StylusPointCollection()
                pts.Add(StylusPoint(x1, y1))
                pts.Add(StylusPoint(x2, y2))
                
                if dist > 5.0:
                    angle = math.atan2(dy, dx)
                    head_len = min(dist * 0.4, max(14.0, self.current_thickness * 3.0))
                    head_angle = math.pi / 6.0 # 30 degrees
                    
                    hx1 = x2 - head_len * math.cos(angle - head_angle)
                    hy1 = y2 - head_len * math.sin(angle - head_angle)
                    hx2 = x2 - head_len * math.cos(angle + head_angle)
                    hy2 = y2 - head_len * math.sin(angle + head_angle)
                    
                    pts.Add(StylusPoint(hx1, hy1))
                    pts.Add(StylusPoint(x2, y2))
                    pts.Add(StylusPoint(hx2, hy2))
                
                self.temp_stroke = Stroke(pts, da)
                self.ink_canvas.Strokes.Add(self.temp_stroke)

    def _on_canvas_mouse_up(self, sender, e):
        if self.shape_start:
            self.shape_start = None
            self.temp_stroke = None
            self.ink_canvas.ReleaseMouseCapture()

    def _on_clear_clicked(self, sender, e):
        self.ink_canvas.Strokes.Clear()

    def _on_key_down(self, sender, e):
        if e.Key == Key.Escape:
            self.Close()

    def _on_send_clicked(self, sender, e):
        try:
            w = int(self.ink_canvas.ActualWidth)
            h = int(self.ink_canvas.ActualHeight)
            
            if w <= 0 or h <= 0:
                w = int(self.ink_canvas.Width)
                h = int(self.ink_canvas.Height)
                
            rtb = RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32)
            rtb.Render(self.ink_canvas)
            
            encoder = PngBitmapEncoder()
            encoder.Frames.Add(BitmapFrame.Create(rtb))
            
            if not os.path.exists(SAVE_DIR):
                os.makedirs(SAVE_DIR)
            if not os.path.exists(SCREENSHOTS_DIR):
                os.makedirs(SCREENSHOTS_DIR)
                
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            timestamped_path = os.path.join(SCREENSHOTS_DIR, "user_snip_{}.png".format(ts))
            
            import System.IO
            ms = System.IO.MemoryStream()
            encoder.Save(ms)
            bytes_data = ms.ToArray()
            raw_bytes = bytes(bytes_data)
            
            # Save to dedicated user snip files
            with open(USER_SNIP_PNG, "wb") as f:
                f.write(raw_bytes)
            # Also update latest_screenshot for unified access
            with open(LATEST_PNG, "wb") as f:
                f.write(raw_bytes)
            # Timestamped history archive
            with open(timestamped_path, "wb") as f:
                f.write(raw_bytes)
                
            meta = {
                "source": "user",
                "captured_by": "user",
                "type": "user_annotated_snip",
                "timestamp": ts,
                "file_path": USER_SNIP_PNG,
                "latest_screenshot_path": LATEST_PNG,
                "history_path": timestamped_path,
                "width": w,
                "height": h,
                "description": "User screen region snip with markup/annotations"
            }
            with open(USER_SNIP_JSON, "w") as jf:
                json.dump(meta, jf, indent=2)
            with open(LATEST_JSON, "w") as jf:
                json.dump(meta, jf, indent=2)
                
            self.Close()
            
            if self.on_saved_callback:
                self.on_saved_callback(meta)
                
        except Exception as ex:
            MessageBox.Show("Error saving markup: " + str(ex), "Revit MCP")


class ScreenSnipOverlay(Window):
    """Fullscreen overlay displaying the captured desktop with real-time bright cutout selection."""
    def __init__(self, full_bmp, origin_x, origin_y, on_cropped_callback=None):
        super(ScreenSnipOverlay, self).__init__()
        self.full_bmp = full_bmp
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.on_cropped_callback = on_cropped_callback
        
        self.start_pt = None
        self.is_selecting = False
        
        self.Title = "Revit MCP Screen Snip"
        self.WindowStyle = getattr(WindowStyle, "None")
        self.AllowsTransparency = False
        self.Topmost = True
        self.ShowInTaskbar = False
        self.Cursor = Cursors.Cross
        
        self.Left = origin_x
        self.Top = origin_y
        self.Width = full_bmp.Width
        self.Height = full_bmp.Height
        
        self.init_ui()

    def init_ui(self):
        self.screen_source = bitmap_to_bitmap_source(self.full_bmp)
        
        self.canvas = Canvas()
        self.canvas.Width = self.Width
        self.canvas.Height = self.Height
        
        bg_brush = ImageBrush(self.screen_source)
        bg_brush.Stretch = Stretch.Fill
        self.canvas.Background = bg_brush
        
        # Dim overlay path with CombinedGeometry (Exclude mode cuts out bright selection area)
        self.full_screen_rect = RectangleGeometry(Rect(0, 0, self.Width, self.Height))
        self.cutout_rect = RectangleGeometry(Rect(0, 0, 0, 0))
        self.combined_geom = CombinedGeometry(GeometryCombineMode.Exclude, self.full_screen_rect, self.cutout_rect)
        
        self.dim_path = WpfPath()
        self.dim_path.Data = self.combined_geom
        self.dim_path.Fill = SolidColorBrush(Color.FromArgb(115, 0, 0, 0))
        self.canvas.Children.Add(self.dim_path)
        
        # Selection highlight border (dashed cyan line)
        self.selection_border = WpfRectShape()
        self.selection_border.Stroke = SolidColorBrush(Color.FromRgb(52, 152, 219))
        self.selection_border.StrokeThickness = 2
        
        dash_col = DoubleCollection()
        dash_col.Add(4.0)
        dash_col.Add(2.0)
        self.selection_border.StrokeDashArray = dash_col
        self.selection_border.Visibility = Visibility.Collapsed
        self.canvas.Children.Add(self.selection_border)
        
        # Dimension badge
        self.dim_badge = Border()
        self.dim_badge.Background = SolidColorBrush(Color.FromArgb(220, 20, 20, 28))
        self.dim_badge.CornerRadius = CornerRadius(4)
        self.dim_badge.Padding = Thickness(6, 2, 6, 2)
        self.dim_badge.Visibility = Visibility.Collapsed
        
        self.dim_badge_txt = TextBlock()
        self.dim_badge_txt.FontSize = 10
        self.dim_badge_txt.FontWeight = FontWeights.SemiBold
        self.dim_badge_txt.Foreground = SolidColorBrush(Color.FromRgb(255, 255, 255))
        self.dim_badge.Child = self.dim_badge_txt
        self.canvas.Children.Add(self.dim_badge)
        
        # Hint bar at the top
        hint_border = Border()
        hint_border.Background = SolidColorBrush(Color.FromArgb(220, 20, 20, 28))
        hint_border.CornerRadius = CornerRadius(6)
        hint_border.Padding = Thickness(16, 8, 16, 8)
        hint_border.Margin = Thickness(0, 20, 0, 0)
        
        hint_txt = TextBlock()
        hint_txt.Text = "✂️ Click and drag to select region | ESC to cancel"
        hint_txt.FontSize = 13
        hint_txt.FontWeight = FontWeights.Medium
        hint_txt.Foreground = SolidColorBrush(Color.FromRgb(255, 255, 255))
        hint_border.Child = hint_txt
        
        Canvas.SetLeft(hint_border, (self.Width - 420) / 2)
        Canvas.SetTop(hint_border, 20)
        self.canvas.Children.Add(hint_border)
        
        self.Content = self.canvas
        
        self.MouseDown += self._on_mouse_down
        self.MouseMove += self._on_mouse_move
        self.MouseUp += self._on_mouse_up
        self.KeyDown += self._on_key_down

    def _on_mouse_down(self, sender, e):
        if e.LeftButton == MouseButtonState.Pressed:
            self.start_pt = e.GetPosition(self)
            self.is_selecting = True
            self.selection_border.Visibility = Visibility.Visible
            self.dim_badge.Visibility = Visibility.Visible
            self._update_cutout(self.start_pt.X, self.start_pt.Y, 0, 0)

    def _on_mouse_move(self, sender, e):
        if self.is_selecting and self.start_pt:
            cur = e.GetPosition(self)
            x = min(self.start_pt.X, cur.X)
            y = min(self.start_pt.Y, cur.Y)
            w = abs(self.start_pt.X - cur.X)
            h = abs(self.start_pt.Y - cur.Y)
            self._update_cutout(x, y, w, h)

    def _update_cutout(self, x, y, w, h):
        self.cutout_rect.Rect = Rect(x, y, w, h)
        
        Canvas.SetLeft(self.selection_border, x)
        Canvas.SetTop(self.selection_border, y)
        self.selection_border.Width = w
        self.selection_border.Height = h
        
        self.dim_badge_txt.Text = "{} × {} px".format(int(w), int(h))
        Canvas.SetLeft(self.dim_badge, x + max(0, w - 80))
        Canvas.SetTop(self.dim_badge, y + h + 6 if y + h + 30 < self.Height else y - 24)

    def _on_mouse_up(self, sender, e):
        if self.is_selecting and self.start_pt:
            self.is_selecting = False
            cur = e.GetPosition(self)
            
            x = int(min(self.start_pt.X, cur.X))
            y = int(min(self.start_pt.Y, cur.Y))
            w = int(abs(self.start_pt.X - cur.X))
            h = int(abs(self.start_pt.Y - cur.Y))
            
            self.Close()
            
            if w > 20 and h > 20:
                try:
                    src_rect = DrawingRectangle(x, y, min(w, self.full_bmp.Width - x), min(h, self.full_bmp.Height - y))
                    cropped = self.full_bmp.Clone(src_rect, self.full_bmp.PixelFormat)
                    if self.on_cropped_callback:
                        self.on_cropped_callback(cropped)
                except Exception as ex:
                    MessageBox.Show("Error cropping screen: " + str(ex), "Revit MCP")

    def _on_key_down(self, sender, e):
        if e.Key == Key.Escape:
            self.Close()


def launch_snipper(on_saved_callback=None):
    """Main entry point to capture screen, show selection overlay, and open annotation editor."""
    bmp, min_x, min_y, w, h = capture_all_screens()
    
    def on_cropped(cropped_bmp):
        editor = AnnotationWindow(cropped_bmp, on_saved_callback)
        editor.Show()
        
    overlay = ScreenSnipOverlay(bmp, min_x, min_y, on_cropped)
    overlay.Show()
