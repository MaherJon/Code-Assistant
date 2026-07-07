"""Visualization tools: CreateVisualization for generating charts and graphs."""

import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from codeassistant.tools.base import Tool, ToolPermission, ToolResult

logger = logging.getLogger("codeassistant.tools.viz")

# ─── Chart type definitions ─────────────────────────────────────────

VALID_CHART_TYPES = ["line", "bar", "scatter", "pie", "histogram", "box", "area", "heatmap"]

CHART_TYPE_REQUIREMENTS = {
    "line":      {"x": True,  "y": True},
    "bar":       {"x": True,  "y": True},
    "scatter":   {"x": True,  "y": True},
    "pie":       {"x": False, "y": True},
    "histogram": {"x": True,  "y": False},
    "box":       {"x": True,  "y": True},
    "area":      {"x": True,  "y": True},
    "heatmap":   {"x": False, "y": False},
}


class CreateVisualization(Tool):
    """Create data visualizations (charts, graphs) from data.

    Supports JSON data, CSV data, or file paths to data files.
    Saves the chart as a PNG image file using matplotlib.
    """

    name = "create_visualization"
    description = (
        "Create data visualizations (charts, graphs) from data. "
        "Supports JSON data, CSV data, or file paths to data files. "
        "Saves the chart as a PNG image file. "
        "Use this when the user asks to visualize, chart, plot, or graph data. "
        "Requires matplotlib (install with: pip install matplotlib)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": (
                    "The data to visualize. Can be one of: "
                    "(1) a JSON string representing a list of objects, "
                    "(2) a CSV string with header row, or "
                    "(3) a file path to a .json or .csv file."
                ),
            },
            "chart_type": {
                "type": "string",
                "enum": VALID_CHART_TYPES,
                "description": "The type of chart to create. Default: 'bar'.",
            },
            "output_path": {
                "type": "string",
                "description": "File path for the output PNG image. Default: 'chart.png'.",
            },
            "title": {
                "type": "string",
                "description": "Title displayed at the top of the chart.",
            },
            "x_column": {
                "type": "string",
                "description": "Name of the column to use for the X axis.",
            },
            "y_column": {
                "type": "string",
                "description": (
                    "Name of the column to use for the Y axis. "
                    "For multi-series charts, use comma-separated column names. "
                    "For pie charts, this is the values column."
                ),
            },
            "data_format": {
                "type": "string",
                "enum": ["json", "csv", "auto"],
                "description": "Format of the data input. 'auto' detects format automatically. Default: 'auto'.",
            },
            "color_palette": {
                "type": "string",
                "description": "Matplotlib colormap name (e.g. 'viridis', 'plasma', 'Blues', 'Set2'). Default: 'Set2'.",
            },
            "figsize": {
                "type": "string",
                "description": "Figure size as 'width,height' in inches. Default: '10,6'.",
            },
        },
        "required": ["data"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    # ─── Main execute ─────────────────────────────────────────────────

    async def execute(
        self,
        data: str,
        chart_type: str = "bar",
        output_path: str = "chart.png",
        title: str = "",
        x_column: str = "",
        y_column: str = "",
        data_format: str = "auto",
        color_palette: str = "Set2",
        figsize: str = "10,6",
    ) -> ToolResult:
        """Create a chart from the provided data and save to a file.

        Args:
            data: JSON/CSV data string or file path.
            chart_type: One of line, bar, scatter, pie, histogram, box, area, heatmap.
            output_path: Where to save the PNG file.
            title: Chart title.
            x_column: Column name for X axis.
            y_column: Column name(s) for Y axis (comma-separated for multi-series).
            data_format: 'json', 'csv', or 'auto'.
            color_palette: Matplotlib colormap name.
            figsize: Figure dimensions as 'width,height'.

        Returns:
            ToolResult with chart metadata.
        """
        # Validate chart_type
        if chart_type not in VALID_CHART_TYPES:
            return ToolResult.fail(
                f"Unknown chart type: '{chart_type}'. "
                f"Valid types: {', '.join(VALID_CHART_TYPES)}"
            )

        # Check matplotlib availability (lazy import)
        mpl_err = self._check_matplotlib()
        if mpl_err:
            return ToolResult.fail(mpl_err)

        # Parse data
        result = self._parse_data(data, data_format)
        if isinstance(result, ToolResult):
            return result
        records, columns = result

        if not records:
            return ToolResult.fail("Data is empty. Provide at least one data record.")

        # Parse y_column list (supports comma-separated for multi-series)
        y_columns = [c.strip() for c in y_column.split(",") if c.strip()] if y_column else []

        # Validate columns
        col_err = self._validate_columns(columns, x_column, y_columns, chart_type)
        if col_err:
            return col_err

        # Parse figsize
        try:
            parts = figsize.split(",")
            fig_w, fig_h = float(parts[0].strip()), float(parts[1].strip())
        except (ValueError, IndexError):
            fig_w, fig_h = 10.0, 6.0

        # Resolve output path
        resolved_path = self._resolve_path(output_path)
        try:
            parent = os.path.dirname(resolved_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        except OSError as e:
            return ToolResult.fail(f"Error creating output directory: {e}")

        # Compute statistics (using numpy if available)
        stats = self._compute_statistics(records, x_column, y_columns)

        # Create the chart
        try:
            chart_err = self._draw_chart(
                records=records,
                columns=columns,
                chart_type=chart_type,
                x_column=x_column,
                y_columns=y_columns,
                title=title,
                output_path=resolved_path,
                color_palette=color_palette,
                figsize=(fig_w, fig_h),
            )
            if chart_err:
                return ToolResult.fail(chart_err)
        except Exception as e:
            logger.error("Chart creation failed: %s", e, exc_info=True)
            return ToolResult.fail(f"Error creating chart: {e}")

        # Build concise output (under 200 chars for renderer truncation)
        n_records = len(records)
        stat_str = ""
        if stats:
            stat_str = f" | mean={stats.get('mean', 'N/A')}"

        output_msg = (
            f"Chart saved: {output_path} "
            f"({chart_type}, {n_records} pts, {fig_w:.0f}x{fig_h:.0f}{stat_str})"
        )
        # Truncate if still too long
        if len(output_msg) > 190:
            output_msg = output_msg[:187] + "..."

        return ToolResult.ok(output_msg, **{
            "chart_type": chart_type,
            "output_path": resolved_path,
            "data_points": n_records,
            "title": title or "(none)",
            "figsize": f"{fig_w:.0f}x{fig_h:.0f}",
            **stats,
        })

    # ─── Path resolution ──────────────────────────────────────────────

    def _resolve_path(self, path: str) -> str:
        """Resolve a file path relative to working directory."""
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.working_dir, path))

    # ─── Dependency check ─────────────────────────────────────────────

    def _check_matplotlib(self) -> Optional[str]:
        """Check if matplotlib is available. Returns error message or None."""
        try:
            import matplotlib  # noqa: F401
            return None
        except ImportError:
            return (
                "matplotlib is not installed. "
                "Install it with: pip install matplotlib\n"
                "For better styling also install: pip install seaborn"
            )

    # ─── Data parsing ─────────────────────────────────────────────────

    def _parse_data(
        self, data: str, data_format: str
    ) -> "Tuple[List[Dict[str, Any]], List[str]] | ToolResult":
        """Parse input data into (records, columns) or return ToolResult on error.

        Auto-detects format when data_format is 'auto':
        - If data looks like valid JSON array → parse as JSON
        - If first line has commas → parse as CSV
        - If it's a path to an existing file → read file and detect by extension
        """
        stripped = data.strip()

        if data_format == "auto":
            # Check if it's a file path
            resolved = self._resolve_path(stripped)
            if os.path.isfile(resolved):
                data_format = "file"
            elif stripped.startswith("[") or stripped.startswith("{"):
                data_format = "json"
            elif "," in stripped.split("\n")[0] if "\n" in stripped else "," in stripped:
                data_format = "csv"
            else:
                return ToolResult.fail(
                    "Could not auto-detect data format. "
                    "Provide data as JSON (starts with [ or {), "
                    "CSV (comma-separated with header row), "
                    "or a valid file path. "
                    "Or specify data_format explicitly."
                )

        if data_format == "file":
            resolved = self._resolve_path(stripped)
            if not os.path.isfile(resolved):
                return ToolResult.fail(f"Data file not found: {stripped}")
            try:
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                return ToolResult.fail(f"Error reading data file: {e}")
            # Detect by extension
            ext = os.path.splitext(resolved)[1].lower()
            if ext == ".json":
                return self._parse_json(content)
            elif ext == ".csv":
                return self._parse_csv(content)
            else:
                # Try JSON first, then CSV
                if content.strip().startswith("[") or content.strip().startswith("{"):
                    return self._parse_json(content)
                return self._parse_csv(content)

        elif data_format == "json":
            return self._parse_json(stripped)

        elif data_format == "csv":
            return self._parse_csv(stripped)

        return ToolResult.fail(f"Unknown data_format: {data_format}")

    def _parse_json(self, text: str) -> "Tuple[List[Dict], List[str]] | ToolResult":
        """Parse JSON text into (records, columns)."""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            return ToolResult.fail(f"Invalid JSON data: {e}")

        if isinstance(parsed, dict):
            # Single object → wrap in list
            parsed = [parsed]
        if not isinstance(parsed, list):
            return ToolResult.fail("JSON data must be a list of objects or a single object.")
        if len(parsed) == 0:
            return ToolResult.fail("JSON data is an empty array.")

        # Collect all keys from all objects (union)
        columns = []
        seen = set()
        for obj in parsed:
            if not isinstance(obj, dict):
                return ToolResult.fail("JSON data must contain objects (dictionaries).")
            for key in obj:
                if key not in seen:
                    columns.append(key)
                    seen.add(key)

        return parsed, columns

    def _parse_csv(self, text: str) -> "Tuple[List[Dict], List[str]] | ToolResult":
        """Parse CSV text into (records, columns)."""
        if not text.strip():
            return ToolResult.fail("CSV data is empty.")

        try:
            reader = csv.DictReader(io.StringIO(text))
            records = list(reader)
        except Exception as e:
            return ToolResult.fail(f"Error parsing CSV data: {e}")

        if not records:
            return ToolResult.fail("CSV data has no data rows (only header or empty).")

        columns = list(records[0].keys()) if records else []
        return records, columns

    # ─── Column validation ────────────────────────────────────────────

    def _validate_columns(
        self,
        columns: List[str],
        x_column: str,
        y_columns: List[str],
        chart_type: str,
    ) -> Optional[ToolResult]:
        """Validate that required columns exist in the data.

        Returns ToolResult.fail if validation fails, None if OK.
        """
        req = CHART_TYPE_REQUIREMENTS.get(chart_type, {"x": False, "y": False})

        if req["x"] and not x_column:
            return ToolResult.fail(
                f"Chart type '{chart_type}' requires x_column. "
                f"Available columns: {', '.join(columns)}"
            )
        if req["y"] and not y_columns:
            return ToolResult.fail(
                f"Chart type '{chart_type}' requires y_column. "
                f"Available columns: {', '.join(columns)}"
            )

        # Check x_column exists
        if x_column and x_column not in columns:
            return ToolResult.fail(
                f"Column '{x_column}' not found in data. "
                f"Available columns: {', '.join(columns)}"
            )

        # Check y_columns exist
        for yc in y_columns:
            if yc and yc not in columns:
                return ToolResult.fail(
                    f"Column '{yc}' not found in data. "
                    f"Available columns: {', '.join(columns)}"
                )

        return None

    # ─── Statistics ───────────────────────────────────────────────────

    def _compute_statistics(
        self,
        records: List[Dict],
        x_column: str,
        y_columns: List[str],
    ) -> Dict[str, Any]:
        """Compute basic statistics for numeric columns using numpy if available."""
        stats: Dict[str, Any] = {}

        # Collect all numeric columns to analyze
        target_cols = list(y_columns)
        if x_column and x_column not in target_cols:
            target_cols.append(x_column)

        for col in target_cols:
            if not col:
                continue
            values = []
            for r in records:
                try:
                    values.append(float(r.get(col, 0)))
                except (ValueError, TypeError):
                    continue

            if not values:
                continue

            # Use numpy if available
            try:
                import numpy as np
                arr = np.array(values)
                stats[f"{col}_mean"] = round(float(np.mean(arr)), 2)
                stats[f"{col}_median"] = round(float(np.median(arr)), 2)
                stats[f"{col}_std"] = round(float(np.std(arr)), 2)
                stats[f"{col}_min"] = round(float(np.min(arr)), 2)
                stats[f"{col}_max"] = round(float(np.max(arr)), 2)
                stats[f"{col}_sum"] = round(float(np.sum(arr)), 2)
            except ImportError:
                # Pure Python fallback
                n = len(values)
                mean_val = sum(values) / n
                sorted_vals = sorted(values)
                median_val = sorted_vals[n // 2]
                variance = sum((v - mean_val) ** 2 for v in values) / n
                stats[f"{col}_mean"] = round(mean_val, 2)
                stats[f"{col}_median"] = round(median_val, 2)
                stats[f"{col}_std"] = round(variance ** 0.5, 2)
                stats[f"{col}_min"] = round(min(values), 2)
                stats[f"{col}_max"] = round(max(values), 2)
                stats[f"{col}_sum"] = round(sum(values), 2)

        # Flatten: also provide top-level mean/median/min/max from first numeric column
        first_col = target_cols[0] if target_cols else None
        if first_col and f"{first_col}_mean" in stats:
            stats["mean"] = stats[f"{first_col}_mean"]
            stats["median"] = stats[f"{first_col}_median"]
            stats["std"] = stats[f"{first_col}_std"]
            stats["min"] = stats[f"{first_col}_min"]
            stats["max"] = stats[f"{first_col}_max"]
            stats["count"] = sum(
                1 for r in records
                if r.get(first_col) not in (None, "")
            )

        return stats

    # ─── Chart dispatch ───────────────────────────────────────────────

    def _draw_chart(
        self,
        records: List[Dict],
        columns: List[str],
        chart_type: str,
        x_column: str,
        y_columns: List[str],
        title: str,
        output_path: str,
        color_palette: str,
        figsize: Tuple[float, float],
    ) -> Optional[str]:
        """Dispatch to the appropriate chart-drawing method. Returns error str or None."""
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt

        # Try to apply seaborn style
        try:
            import seaborn as sns
            sns.set_style("whitegrid")
        except ImportError:
            plt.style.use("ggplot")

        # Extract data
        x_values = self._extract_numeric(records, x_column) if x_column else []
        y_series = {}
        for yc in y_columns:
            y_series[yc] = self._extract_numeric(records, yc)

        # Validate color_palette
        try:
            plt.get_cmap(color_palette)
        except (ValueError, AttributeError):
            color_palette = "Set2"

        builders = {
            "line":      self._draw_line,
            "bar":       self._draw_bar,
            "scatter":   self._draw_scatter,
            "pie":       self._draw_pie,
            "histogram": self._draw_histogram,
            "box":       self._draw_box,
            "area":      self._draw_area,
            "heatmap":   self._draw_heatmap,
        }

        draw_fn = builders[chart_type]
        fig = draw_fn(
            records=records,
            columns=columns,
            x_values=x_values if x_column else None,
            x_label=x_column,
            y_series=y_series,
            title=title,
            color_palette=color_palette,
            figsize=figsize,
        )

        if fig is None:
            return "Chart creation returned no figure."

        try:
            fig.savefig(output_path, dpi=100, bbox_inches="tight", facecolor="white")
        finally:
            plt.close(fig)

        return None

    def _extract_numeric(self, records: List[Dict], column: str) -> List[Any]:
        """Extract values from a column, attempting float conversion.

        Returns original string values if conversion fails (for categorical data).
        """
        if not column:
            return []
        result = []
        for r in records:
            val = r.get(column, None)
            if val is None or val == "":
                result.append(None)
                continue
            try:
                result.append(float(val))
            except (ValueError, TypeError):
                result.append(str(val))
        return result

    # ─── Individual chart renderers ───────────────────────────────────

    def _draw_line(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=figsize)

        x = [str(v) if v is not None else "" for v in x_values] if x_values else range(len(records))
        cmap = plt.get_cmap(color_palette)
        colors = [cmap(i / max(len(y_series), 1)) for i in range(len(y_series))]

        for i, (col_name, y_vals) in enumerate(y_series.items()):
            valid = [(xi, yi) for xi, yi in zip(x, y_vals) if yi is not None]
            if not valid:
                continue
            vx, vy = zip(*valid)
            ax.plot(vx, vy, marker="o", linewidth=2, label=col_name,
                   color=colors[i] if i < len(colors) else None)

        self._style_axes(ax, title, x_label, "Value")
        if len(y_series) > 1:
            ax.legend()
        return fig

    def _draw_bar(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        import numpy as np
        fig, ax = plt.subplots(figsize=figsize)

        labels = [str(v) if v is not None else "" for v in x_values] if x_values else range(len(records))
        series_names = list(y_series.keys())
        n_series = len(series_names)
        n_groups = len(labels)

        cmap = plt.get_cmap(color_palette)
        bar_width = 0.8 / max(n_series, 1)
        x_idx = np.arange(n_groups)

        for i, col_name in enumerate(series_names):
            y_vals = y_series[col_name]
            values = [v if v is not None else 0 for v in y_vals]
            offset = (i - (n_series - 1) / 2) * bar_width if n_series > 1 else 0
            color = cmap(i / max(n_series, 1)) if n_series > 1 else cmap(0.5)
            ax.bar(x_idx + offset, values, bar_width, label=col_name, color=color)

        ax.set_xticks(x_idx)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
        self._style_axes(ax, title, x_label, "Value")
        if n_series > 1:
            ax.legend()
        return fig

    def _draw_scatter(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=figsize)

        cmap = plt.get_cmap(color_palette)
        for i, (col_name, y_vals) in enumerate(y_series.items()):
            valid = [(xi, yi) for xi, yi in zip(x_values, y_vals)
                    if xi is not None and yi is not None]
            if not valid:
                continue
            vx, vy = zip(*valid)
            color = cmap(i / max(len(y_series), 1)) if y_series else cmap(0.5)
            ax.scatter(vx, vy, alpha=0.7, label=col_name, color=color, s=50)

        self._style_axes(ax, title, x_label, "Value")
        if len(y_series) > 1:
            ax.legend()
        return fig

    def _draw_pie(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=figsize)

        # Use x_values as labels, first y_series as values
        labels = [str(v) if v is not None else "" for v in x_values] if x_values else [
            str(r.get(list(r.keys())[0], i)) for i, r in enumerate(records)
        ]

        first_y = list(y_series.values())[0] if y_series else []
        values = [v if v is not None else 0 for v in first_y] if first_y else [1] * len(labels)

        cmap = plt.get_cmap(color_palette)
        colors = [cmap(i / max(len(values), 1)) for i in range(len(values))]

        wedges, texts, autotexts = ax.pie(
            values, labels=labels, autopct="%1.1f%%",
            colors=colors, startangle=90,
        )
        for at in autotexts:
            at.set_fontsize(9)
        if title:
            ax.set_title(title, fontsize=13, fontweight="bold", pad=15)
        return fig

    def _draw_histogram(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=figsize)

        values = [v for v in x_values if v is not None and isinstance(v, (int, float))]
        if not values:
            # Try first numeric column from records
            for col in columns:
                nums = self._extract_numeric(records, col)
                nums = [n for n in nums if n is not None and isinstance(n, (int, float))]
                if nums:
                    values = nums
                    x_label = col
                    break

        if not values:
            ax.text(0.5, 0.5, "No numeric data for histogram", transform=ax.transAxes, ha="center")
            return fig

        cmap = plt.get_cmap(color_palette)
        ax.hist(values, bins=20, color=cmap(0.5), edgecolor="white", alpha=0.8)
        self._style_axes(ax, title, x_label or "Value", "Frequency")
        return fig

    def _draw_box(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=figsize)

        # Group y values by x categories
        categories = [str(v) if v is not None else "N/A" for v in x_values] if x_values else ["All"]
        first_y_name = list(y_series.keys())[0] if y_series else ""
        first_y = list(y_series.values())[0] if y_series else []

        # Build grouped data
        grouped = {}
        for cat, yv in zip(categories, first_y):
            if cat not in grouped:
                grouped[cat] = []
            if yv is not None:
                grouped[cat].append(yv)

        data_to_plot = [vals for vals in grouped.values() if vals]
        plot_labels = [cat for cat, vals in grouped.items() if vals]

        if not data_to_plot:
            ax.text(0.5, 0.5, "No numeric data for box plot", transform=ax.transAxes, ha="center")
            return fig

        cmap = plt.get_cmap(color_palette)
        bp = ax.boxplot(data_to_plot, patch_artist=True)
        ax.set_xticklabels(plot_labels, rotation=45, ha="right", fontsize=9)
        for patch in bp["boxes"]:
            patch.set_facecolor(cmap(0.5))
            patch.set_alpha(0.7)

        ax.tick_params(axis="x", rotation=45)
        self._style_axes(ax, title, x_label, first_y_name or "Value")
        return fig

    def _draw_area(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=figsize)

        x = [str(v) if v is not None else "" for v in x_values] if x_values else range(len(records))
        x_idx = range(len(x))
        cmap = plt.get_cmap(color_palette)

        for i, (col_name, y_vals) in enumerate(y_series.items()):
            values = [v if v is not None else 0 for v in y_vals]
            color = cmap(i / max(len(y_series), 1)) if y_series else cmap(0.5)
            ax.fill_between(x_idx, values, alpha=0.5, label=col_name, color=color)
            ax.plot(x_idx, values, color=color, linewidth=1.5)

        ax.set_xticks(x_idx)
        ax.set_xticklabels(x, rotation=45, ha="right", fontsize=9)
        self._style_axes(ax, title, x_label, "Value")
        if len(y_series) > 1:
            ax.legend()
        return fig

    def _draw_heatmap(
        self, records, columns, x_values, x_label, y_series, title, color_palette, figsize,
    ):
        import matplotlib.pyplot as plt
        import numpy as np
        fig, ax = plt.subplots(figsize=figsize)

        # Build matrix from numeric columns
        numeric_cols = []
        for col in columns:
            vals = self._extract_numeric(records, col)
            if vals and all(isinstance(v, (int, float)) or v is None for v in vals):
                numeric_cols.append(col)

        if not numeric_cols:
            ax.text(0.5, 0.5, "No numeric columns for heatmap", transform=ax.transAxes, ha="center")
            return fig

        # Build matrix
        matrix = []
        for col in numeric_cols:
            row = []
            for r in records:
                val = r.get(col, 0)
                try:
                    row.append(float(val))
                except (ValueError, TypeError):
                    row.append(0.0)
            matrix.append(row)

        if not matrix:
            return fig

        matrix = np.array(matrix)

        # Use record index or first string column as column labels
        col_labels = [str(i + 1) for i in range(matrix.shape[1])]
        row_labels = numeric_cols

        cmap = plt.get_cmap(color_palette)
        im = ax.imshow(matrix, aspect="auto", cmap=cmap)

        ax.set_xticks(range(len(col_labels)))
        ax.set_xticklabels(col_labels, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(row_labels)))
        ax.set_yticklabels(row_labels, fontsize=9)

        if title:
            ax.set_title(title, fontsize=13, fontweight="bold")
        plt.colorbar(im, ax=ax)
        return fig

    # ─── Style helper ─────────────────────────────────────────────────

    def _style_axes(self, ax, title: str, x_label: str, y_label: str) -> None:
        """Apply common styling to axes."""
        if title:
            ax.set_title(title, fontsize=13, fontweight="bold")
        if x_label:
            ax.set_xlabel(x_label, fontsize=10)
        if y_label:
            ax.set_ylabel(y_label, fontsize=10)
        ax.tick_params(labelsize=9)
        ax.grid(True, alpha=0.3)
