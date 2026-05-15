"""
DNG Pipeline Publisher
Maya PySide2 tool for publishing model assets with LOD support.

Usage (run inside Maya Script Editor):
    import importlib, sys
    # sys.path.append(r"M:\pipeline\tools")
    import dng_publisher
    importlib.reload(dng_publisher)
    dng_publisher.show()

Changelog v2.4:
  - UI: Publish tab redesigned to compact horizontal layout (2-column grid).
  - NEW: File Converter rebuilt as scene-query workflow:
      • Select any group / ASS standin node in the scene
      • Tool queries the publish path from the node's file attribute
      • Derives all sibling LOD paths from the path structure
      • Operations: ABC→ASS, ASS→ABC, ASS→import .ma, MA groups→overwrite publish

Changelog v2.3:
  - FIX: All LODs now export at division level 0 (no smoothing applied).
  - FIX: Duplicate group rename no longer corrupts names containing _001_
  - FIX: Publish button is now visibly active / orange at all times.

Changelog v2.2:
  - FIX: ASS export now uses the correct per-LOD subdivision level
  - OVERHAUL: Convert tab rebuilt with single input path + output folder.
"""

import os
import re

_SWITCHER_AVAILABLE = True
try:
    import dng_switcher
except Exception:
    _SWITCHER_AVAILABLE = False

import maya.cmds as cmds

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Qt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT_DEFAULT = r"M:\projects\GD\asset\sets"
KICK_DEFAULT = r"C:\Program Files\Autodesk\Arnold\maya2024\bin\kick.exe"

LOD_CONFIG = {
    "hi":  {"div": 0, "suffix": "_hi"},
    "mid": {"div": 0, "suffix": "_mid"},
    "lo":  {"div": 0, "suffix": "_lo"},
}

SUBDIV_TYPES = ["Maya Catmull-Clark", "OpenSubdiv Catmull-Clark"]

# ---------------------------------------------------------------------------
# Dark stylesheet
# ---------------------------------------------------------------------------

STYLE = """
QWidget { background:#2b2b2b; color:#cccccc; font-family:"Segoe UI",Arial,sans-serif; font-size:11px; }
QMainWindow, QDialog { background:#2b2b2b; }
QLabel { color:#bbbbbb; }
QLabel#header { color:#e6962f; font-size:13px; font-weight:bold; }
QLabel#sectionTitle { color:#aaaaaa; font-size:10px; background:#3a3a3a;
                      padding:3px 8px; border-top:1px solid #555; border-bottom:1px solid #1a1a1a; }
QLineEdit, QTextEdit, QPlainTextEdit {
    background:#1e1e1e; border:1px solid #555; border-radius:2px;
    color:#dddddd; padding:3px 6px; selection-background-color:#e6962f; selection-color:#1a1a1a; }
QLineEdit:focus, QTextEdit:focus { border:1px solid #e6962f; }
QComboBox { background:#1e1e1e; border:1px solid #555; border-radius:2px; color:#ddd; padding:2px 6px; }
QComboBox::drop-down { border:none; width:18px; }
QComboBox QAbstractItemView { background:#1e1e1e; selection-background-color:#e6962f; selection-color:#1a1a1a; }
QRadioButton, QCheckBox { color:#bbbbbb; spacing:5px; }
QRadioButton::indicator, QCheckBox::indicator { width:13px; height:13px; border:1px solid #666; border-radius:2px; background:#1e1e1e; }
QRadioButton::indicator { border-radius:7px; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked { background:#e6962f; border-color:#e6962f; }
QPushButton {
    background:#444; border:1px solid #555; border-radius:2px; color:#ccc;
    padding:4px 12px; min-width:60px; }
QPushButton:hover { background:#555; }
QPushButton:pressed { background:#333; }
QPushButton#btnPublish {
    background:#e6962f; color:#1a1a1a; font-weight:bold;
    border:1px solid #f0a840; font-size:12px; padding:6px 20px; min-width:90px; }
QPushButton#btnPublish:hover  { background:#f5aa45; border-color:#f5aa45; }
QPushButton#btnPublish:pressed { background:#cc7a1a; }
QPushButton#btnAction {
    background:#2a4a6a; color:#7ab8e6; font-weight:bold;
    border:1px solid #3a6a9a; padding:5px 12px; }
QPushButton#btnAction:hover { background:#3a5a7a; }
QPushButton#btnAction:pressed { background:#1a3a5a; }
QPushButton#btnQuery {
    background:#3a4a2a; color:#9fc860; font-weight:bold;
    border:1px solid #5a7a3a; padding:5px 16px; }
QPushButton#btnQuery:hover { background:#4a5a3a; }
QPushButton#btnWarn {
    background:#6a3a2a; color:#f0a87a; font-weight:bold;
    border:1px solid #9a5a3a; padding:5px 12px; }
QPushButton#btnWarn:hover { background:#7a4a3a; }
QTabWidget::pane { border:none; background:#2b2b2b; }
QTabBar::tab { background:#2b2b2b; color:#888; padding:6px 18px; border-right:1px solid #1a1a1a; }
QTabBar::tab:selected { background:#353535; color:#e6962f; border-bottom:2px solid #e6962f; }
QTabBar::tab:hover:!selected { background:#333; color:#bbb; }
QFrame#card { background:#353535; border:1px solid #444; border-radius:3px; }
QFrame#infoCard { background:#1e2a1e; border:1px solid #3a5a3a; border-radius:3px; }
QFrame#warnCard { background:#2a2010; border:1px solid #6a5020; border-radius:3px; }
QGroupBox { border:1px solid #444; border-radius:3px; margin-top:6px; color:#aaa; }
QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; color:#aaa; }
QScrollBar:vertical { background:#1e1e1e; width:8px; }
QScrollBar::handle:vertical { background:#555; border-radius:4px; min-height:20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_available_sets(root):
    if not os.path.isdir(root):
        return []
    return sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])


def _next_work_version(work_root):
    if not os.path.isdir(work_root):
        return "v001"
    versions = [item for item in os.listdir(work_root) if re.match(r"v\d+$", item)]
    if not versions:
        return "v001"
    nums = []
    for v in versions:
        try:
            nums.append(int(v[1:]))
        except:
            pass
    return "v001" if not nums else "v{:03d}".format(max(nums) + 1)


def _latest_work_version(work_root):
    """Return the latest existing version string, or None."""
    if not os.path.isdir(work_root):
        return None
    versions = [item for item in os.listdir(work_root) if re.match(r"v\d+$", item)]
    if not versions:
        return None
    nums = []
    for v in versions:
        try:
            nums.append(int(v[1:]))
        except:
            pass
    return None if not nums else "v{:03d}".format(max(nums))


def _build_paths(root, set_name, asset, lod, version):
    base = os.path.join(root, set_name, "publish", "elements", asset, "mod")
    work_dir = os.path.join(base, "work", version)
    publish_dir = os.path.join(base, "publish", lod)
    work_stem = "dng_{}_mod_{}".format(asset, version)
    publish_stem = "dng_{}_mod_{}".format(asset, lod)
    return {
        "work_dir": work_dir,
        "publish_dir": publish_dir,
        "work_ma": os.path.join(work_dir, work_stem + ".ma"),
        "ma":  os.path.join(publish_dir, publish_stem + ".ma"),
        "ass": os.path.join(publish_dir, publish_stem + ".ass"),
        "abc": os.path.join(publish_dir, publish_stem + ".abc"),
        "stem": publish_stem,
    }


def _get_lod_groups(sfx_map=None):
    if sfx_map is None:
        sfx_map = {lod: cfg["suffix"] for lod, cfg in LOD_CONFIG.items()}
    result = {lod: [] for lod in sfx_map}
    top_nodes = cmds.ls(assemblies=True, long=False) or []
    for node in top_nodes:
        name_lower = node.lower()
        for lod, sfx in sfx_map.items():
            if sfx.lower() in name_lower:
                result[lod].append(node)
    return result


_MAYA_DUP_RE = re.compile(r"^(.*[A-Za-z\]\)])(1)$")


def _strip_maya_dup_suffix(short_name):
    m = _MAYA_DUP_RE.match(short_name)
    return m.group(1) if m else short_name


def _is_node_type(node, expected_type):
    try:
        return bool(cmds.objExists(node) and cmds.nodeType(node) == expected_type)
    except Exception:
        return False


def _first_parent(node):
    parent = cmds.listRelatives(node, p=True)
    return parent[0] if parent else None


def _get_gpu_cache_path(node):
    if cmds.attributeQuery("cacheFileName", node=node, exists=True):
        return cmds.getAttr("{}.cacheFileName".format(node)) or ""
    for shape in (cmds.listRelatives(node, shapes=True) or []):
        if cmds.attributeQuery("cacheFileName", node=shape, exists=True):
            return cmds.getAttr("{}.cacheFileName".format(shape)) or ""
    return ""


def _get_ass_path(node):
    """Get .dso path from aiStandIn shape (ASS standin)."""
    candidates = [node] + (cmds.listRelatives(node, allDescendents=True, fullPath=True) or [])
    for n in candidates:
        try:
            if cmds.attributeQuery("dso", node=n, exists=True):
                val = cmds.getAttr("{}.dso".format(n)) or ""
                if val:
                    return val
        except Exception:
            pass
    return ""


def _get_node_world_matrix(node):
    """Return world space translation/rotation/scale as dict."""
    try:
        t = cmds.xform(node, q=True, ws=True, t=True) or [0,0,0]
        r = cmds.xform(node, q=True, ws=True, ro=True) or [0,0,0]
        s = cmds.xform(node, q=True, ws=True, s=True) or [1,1,1]
        return {"t": t, "r": r, "s": s}
    except Exception:
        return {"t": [0,0,0], "r": [0,0,0], "s": [1,1,1]}


def _apply_world_matrix(node, xform):
    """Apply stored world xform to node."""
    try:
        cmds.xform(node, ws=True, t=xform["t"])
        cmds.xform(node, ws=True, ro=xform["r"])
        cmds.xform(node, ws=True, s=xform["s"])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Path inference from publish structure
# ---------------------------------------------------------------------------

# Expected publish path pattern:
#   M:\projects\GD\asset\sets\<set>\publish\elements\<asset>\mod\publish\<lod>\dng_<asset>_mod_<lod>.<ext>

_PUBLISH_PATH_RE = re.compile(
    r"(?P<root>.+?[\\/]sets[\\/])"
    r"(?P<set>[^\\/]+)[\\/]"
    r"publish[\\/]elements[\\/]"
    r"(?P<asset>[^\\/]+)[\\/]"
    r"mod[\\/]publish[\\/]"
    r"(?P<lod>hi|mid|lo)[\\/]"
    r"(?P<stem>[^\\/]+)"
    r"\.(?P<ext>ma|ass|abc)$",
    re.IGNORECASE
)


def _parse_publish_path(path):
    """
    Parse a publish file path and return dict with keys:
    root, set, asset, lod, stem, ext
    Returns None if path doesn't match.
    """
    m = _PUBLISH_PATH_RE.match(path.replace("\\", "/").replace("//", "/"))
    if not m:
        # Try with backslashes normalized
        m = _PUBLISH_PATH_RE.match(path)
    if not m:
        return None
    return {
        "root": m.group("root").rstrip("/\\").replace("/", "\\"),
        "set":  m.group("set"),
        "asset": m.group("asset"),
        "lod":  m.group("lod").lower(),
        "stem": m.group("stem"),
        "ext":  m.group("ext").lower(),
    }


def _lod_paths_from_info(info, ext):
    """Given parsed path info, return {hi:.., mid:.., lo:..} for given ext."""
    result = {}
    for lod in ("hi", "mid", "lo"):
        stem = "dng_{}_mod_{}".format(info["asset"], lod)
        publish_dir = os.path.join(
            info["root"], info["set"], "publish", "elements",
            info["asset"], "mod", "publish", lod
        )
        result[lod] = os.path.join(publish_dir, stem + "." + ext)
    return result


def _work_ma_path_from_info(info):
    """Return path to latest work .ma file."""
    work_root = os.path.join(
        info["root"], info["set"], "publish", "elements",
        info["asset"], "mod", "work"
    )
    ver = _latest_work_version(work_root)
    if not ver:
        ver = _next_work_version(work_root)
    stem = "dng_{}_mod_{}".format(info["asset"], ver)
    return os.path.join(work_root, ver, stem + ".ma"), work_root, ver


# ---------------------------------------------------------------------------
# Query selected node's publish path
# ---------------------------------------------------------------------------

def _query_selected_publish_path():
    """
    From the selected node, attempt to find a publish file path.
    Checks: GPU .cacheFileName, ASS .dso, or if it's a mesh group
    whose children have those attrs. Returns (path, node) or (None, None).
    """
    sel = cmds.ls(sl=True) or []
    if not sel:
        return None, None

    node = sel[0]

    # Try GPU cache
    path = _get_gpu_cache_path(node)
    if path:
        return path, node

    # Try ASS standin
    path = _get_ass_path(node)
    if path:
        return path, node

    # Try descendants
    for desc in (cmds.listRelatives(node, allDescendents=True, fullPath=True) or []):
        path = _get_gpu_cache_path(desc)
        if path:
            return path, node
        path = _get_ass_path(desc)
        if path:
            return path, node

    return None, node


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _smooth_duplicate_and_export(groups, div_level, subdiv_type,
                                 ma_path=None, ass_path=None, abc_path=None,
                                 frame_range=(1, 1), abc_flags="", asset_name="asset"):

    if not groups:
        return False

    exported = False
    duplicates = []
    temp_originals = []

    try:

        # ------------------------------------------------------------
        # RENAME ORIGINALS TEMPORARILY
        # ------------------------------------------------------------
        for grp in groups:

            temp_name = grp + "__SRC"

            temp_original = cmds.rename(grp, temp_name)

            temp_originals.append((temp_original, grp))

            # duplicate renamed original
            dup = cmds.duplicate(temp_original)[0]

            # rename duplicate back to original clean name
            dup = cmds.rename(dup, grp)

            duplicates.append(dup)

        # ------------------------------------------------------------
        # CLEAN DUPLICATE NAMES
        # INCLUDING ROOT DUPLICATES
        # ------------------------------------------------------------
        nodes_to_clean = list(duplicates)

        desc = cmds.listRelatives(
            duplicates,
            allDescendents=True,
            fullPath=True
        ) or []

        desc.reverse()

        nodes_to_clean.extend(desc)

        updated_root_names = {}

        for node in nodes_to_clean:

            short = node.split("|")[-1]

            clean = _strip_maya_dup_suffix(short)

            if clean == short:
                continue

            try:
                new_name = cmds.rename(node, clean)

                if node in duplicates:
                    updated_root_names[node] = new_name

            except Exception:
                pass

        duplicates = [updated_root_names.get(d, d) for d in duplicates]

        # ------------------------------------------------------------
        # GET GEO
        # ------------------------------------------------------------
        geo = cmds.listRelatives(
            duplicates,
            allDescendents=True,
            type="mesh",
            fullPath=True
        ) or []

        if not geo:
            return False

        # ------------------------------------------------------------
        # APPLY SMOOTH
        # ------------------------------------------------------------
        if div_level > 0:

            subdiv_flag = 2 if "OpenSubdiv" in subdiv_type else 1

            mesh_transforms = list(set(

                p[0]

                for shape in geo

                for p in [cmds.listRelatives(
                    shape,
                    parent=True,
                    fullPath=True
                ) or []]

                if p
            ))

            for obj in mesh_transforms:

                try:
                    cmds.polySmooth(
                        obj,
                        divisions=div_level,
                        continuity=1,
                        smoothUVs=1,
                        keepBorder=1,
                        subdivisionType=subdiv_flag
                    )

                except Exception:
                    pass

        # ------------------------------------------------------------
        # RESTORE ORIGINAL NAMES BEFORE EXPORT
        # IMPORTANT:
        # Arnold captures hierarchy names during ASS export.
        # If __SRC exists during export it leaks into paths.
        # ------------------------------------------------------------
        restored_duplicates = []

        for dup, (_, original_name) in zip(duplicates, temp_originals):

            final_dup_name = dup

            if cmds.objExists(original_name):

                try:
                    # temporarily move duplicate away
                    temp_dup = cmds.rename(dup, dup + "__EXPORT")
                    final_dup_name = temp_dup

                except Exception:
                    pass

            # restore original source
            for temp_name, orig in temp_originals:

                if orig != original_name:
                    continue

                if cmds.objExists(temp_name):

                    try:
                        cmds.rename(temp_name, orig)

                    except Exception:
                        pass

            # rename duplicate back cleanly
            if cmds.objExists(final_dup_name):

                try:
                    final_dup_name = cmds.rename(final_dup_name, original_name)

                except Exception:
                    pass

            restored_duplicates.append(final_dup_name)

        duplicates = restored_duplicates

        # prevent finally from restoring again
        temp_originals = []

        # ------------------------------------------------------------
        # EXPORT MA
        # ------------------------------------------------------------
        if ma_path:

            os.makedirs(os.path.dirname(ma_path), exist_ok=True)

            cmds.select(duplicates)

            cmds.file(
                ma_path,
                force=True,
                options="v=0;",
                type="mayaAscii",
                exportSelected=True
            )

            exported = True

        # ------------------------------------------------------------
        # EXPORT ASS
        # ------------------------------------------------------------
        if ass_path:

            os.makedirs(os.path.dirname(ass_path), exist_ok=True)

            cmds.arnoldExportAss(
                f=ass_path,
                root=duplicates[0] if len(duplicates) == 1 else duplicates,
                selected=False,
                shadowLinks=1,
                lightLinks=1,
                boundingBox=True,
                startFrame=frame_range[0],
                endFrame=frame_range[0],
            )

            exported = True

        # ------------------------------------------------------------
        # EXPORT ABC
        # ------------------------------------------------------------
        if abc_path:

            os.makedirs(os.path.dirname(abc_path), exist_ok=True)

            fs, fe = frame_range

            extra = (
                abc_flags
                if abc_flags
                else "-uvWrite -worldSpace -writeVisibility"
            )

            job = (
                "-frameRange {fs} {fe} {extra} {roots} -file {path}"
            ).format(
                fs=fs,
                fe=fe,
                extra=extra,
                roots=" ".join([
                    '-root "{}"'.format(x.replace("\\", "/"))
                    for x in duplicates
                ]),
                path=abc_path.replace("\\", "/"),
            )

            cmds.AbcExport(j=job)

            exported = True

        return exported

    finally:

        # ------------------------------------------------------------
        # DELETE DUPLICATES
        # ------------------------------------------------------------
        for dup in duplicates:

            if cmds.objExists(dup):

                try:
                    cmds.delete(dup)

                except Exception:
                    pass

        # ------------------------------------------------------------
        # SAFETY RESTORE
        # only runs if earlier restore failed unexpectedly
        # ------------------------------------------------------------
        for temp_name, original_name in temp_originals:

            if cmds.objExists(temp_name):

                try:
                    cmds.rename(temp_name, original_name)

                except Exception:
                    pass

# def _smooth_duplicate_and_export(groups, div_level, subdiv_type,
#                                  ma_path=None, ass_path=None, abc_path=None,
#                                  frame_range=(1, 1), abc_flags="", asset_name="asset"):
#     if not groups:
#         return False
#
#     exported = False
#     duplicates = []
#     temp_originals = []
#
#     try:
#         for grp in groups:
#             temp_name = grp + "__SRC"
#             temp_original = cmds.rename(grp, temp_name)
#             temp_originals.append((temp_original, grp))
#             dup = cmds.duplicate(temp_original)[0]
#             dup = cmds.rename(dup, grp)
#             duplicates.append(dup)
#
#         nodes_to_clean = list(duplicates)
#         desc = cmds.listRelatives(duplicates, allDescendents=True, fullPath=True) or []
#         desc.reverse()
#         nodes_to_clean.extend(desc)
#
#         updated_root_names = {}
#         for node in nodes_to_clean:
#             short = node.split("|")[-1]
#             clean = _strip_maya_dup_suffix(short)
#             if clean == short:
#                 continue
#             try:
#                 new_name = cmds.rename(node, clean)
#                 if node in duplicates:
#                     updated_root_names[node] = new_name
#             except Exception:
#                 pass
#
#         duplicates = [updated_root_names.get(d, d) for d in duplicates]
#
#         geo = cmds.listRelatives(duplicates, allDescendents=True, type="mesh", fullPath=True) or []
#         if not geo:
#             return False
#
#         if div_level > 0:
#             subdiv_flag = 2 if "OpenSubdiv" in subdiv_type else 1
#             mesh_transforms = list(set(
#                 p[0] for shape in geo
#                 for p in [cmds.listRelatives(shape, parent=True, fullPath=True) or []]
#                 if p
#             ))
#             for obj in mesh_transforms:
#                 try:
#                     cmds.polySmooth(obj, divisions=div_level, continuity=1,
#                                     smoothUVs=1, keepBorder=1, subdivisionType=subdiv_flag)
#                 except Exception:
#                     pass
#
#         if ma_path:
#             os.makedirs(os.path.dirname(ma_path), exist_ok=True)
#             cmds.select(duplicates)
#             cmds.file(ma_path, force=True, options="v=0;", type="mayaAscii", exportSelected=True)
#             exported = True
#
#         if ass_path:
#             os.makedirs(os.path.dirname(ass_path), exist_ok=True)
#             cmds.arnoldExportAss(
#                 f=ass_path,
#                 root=duplicates[0] if len(duplicates) == 1 else duplicates,
#                 selected=False, shadowLinks=1, lightLinks=1, boundingBox=True,
#                 startFrame=frame_range[0], endFrame=frame_range[0],
#             )
#             exported = True
#
#         if abc_path:
#             os.makedirs(os.path.dirname(abc_path), exist_ok=True)
#             fs, fe = frame_range
#             extra = abc_flags if abc_flags else "-uvWrite -worldSpace -writeVisibility"
#             job = "-frameRange {fs} {fe} {extra} {roots} -file {path}".format(
#                 fs=fs, fe=fe, extra=extra,
#                 roots=" ".join(['-root "{}"'.format(x.replace("\\", "/")) for x in duplicates]),
#                 path=abc_path.replace("\\", "/"),
#             )
#             cmds.AbcExport(j=job)
#             exported = True
#
#         return exported
#
#     finally:
#         for dup in duplicates:
#             if cmds.objExists(dup):
#                 try:
#                     cmds.delete(dup)
#                 except Exception:
#                     pass
#         for temp_name, original_name in temp_originals:
#             if cmds.objExists(temp_name):
#                 try:
#                     cmds.rename(temp_name, original_name)
#                 except Exception:
#                     pass


def _convert_ass_to_ma(ass_path, ma_path):
    cmds.file(new=True, force=True)
    if not cmds.pluginInfo("mtoa", query=True, loaded=True):
        cmds.loadPlugin("mtoa")
    try:
        import mtoa.core
        mtoa.core.createOptions()
    except Exception:
        pass
    cmds.arnoldImportAss(f=ass_path, namespace=":")
    cmds.file(rename=ma_path)
    cmds.file(save=True, type="mayaAscii")


def _import_and_export_abc(src_path, abc_out, frame_start, frame_end, abc_flags):
    ns = "_dng_conv_tmp_"
    cmds.file(src_path, i=True, namespace=ns,
              type="mayaAscii" if src_path.endswith(".ma") else "Alembic")
    top_nodes = cmds.ls("{}:*".format(ns), assemblies=True) or []
    extra = abc_flags if abc_flags else "-uvWrite -worldSpace -writeVisibility"
    roots = " ".join(["-root {}".format(n) for n in top_nodes])
    job = "-frameRange {fs} {fe} {extra} {roots} -file {path}".format(
        fs=frame_start, fe=frame_end, extra=extra, roots=roots,
        path=abc_out.replace("\\", "/"),
    )
    try:
        cmds.AbcExport(j=job)
    finally:
        try:
            cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

class DNGPublisher(QtWidgets.QMainWindow):
    WINDOW_TITLE = "DNG Pipeline Publisher  v2.4"
    OBJECT_NAME  = "DNGPublisherWindow"

    def __init__(self, parent=None):
        super(DNGPublisher, self).__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumWidth(700)
        self.setStyleSheet(STYLE)
        self._queried_info = None   # cached from _on_query_node
        self._queried_node = None
        self._queried_xform = None
        self._build_ui()

    # =========================================================================
    # TOP-LEVEL UI
    # =========================================================================

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header
        hdr = QtWidgets.QLabel("  DNG Pipeline Publisher  v2.4")
        hdr.setObjectName("header")
        hdr.setFixedHeight(30)
        hdr.setStyleSheet("background:#1a1a1a; color:#e6962f; font-size:13px;"
                          " font-weight:bold; padding-left:10px;")
        root_layout.addWidget(hdr)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_publish_tab(), "  Publish Model  ")
        self.tabs.addTab(self._build_converter_tab(), "  File Converter  ")
        root_layout.addWidget(self.tabs)

        # Bottom bar
        btn_bar = QtWidgets.QWidget()
        btn_bar.setStyleSheet("background:#222; border-top:1px solid #1a1a1a;")
        btn_layout = QtWidgets.QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(10, 5, 10, 5)

        self.btn_publish = QtWidgets.QPushButton("▶  Publish")
        self.btn_publish.setObjectName("btnPublish")
        self.btn_publish.setEnabled(True)
        self.btn_publish.setStyleSheet(
            "QPushButton { background:#e6962f; color:#1a1a1a; font-weight:bold;"
            " border:1px solid #f0a840; font-size:12px; padding:6px 20px; }"
            "QPushButton:hover { background:#f5aa45; }"
            "QPushButton:pressed { background:#cc7a1a; }"
        )
        self.btn_publish.clicked.connect(self._on_publish)

        self.btn_validate = QtWidgets.QPushButton("Validate Scene")
        self.btn_validate.clicked.connect(self._on_validate)

        btn_clear = QtWidgets.QPushButton("Clear Log")
        btn_clear.clicked.connect(self._clear_log)

        self.status_lbl = QtWidgets.QLabel("● Maya connected")
        self.status_lbl.setStyleSheet("color:#3a7a4a; font-size:10px;")

        btn_layout.addWidget(self.btn_publish)
        btn_layout.addWidget(self.btn_validate)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_clear)
        btn_layout.addWidget(self.status_lbl)
        root_layout.addWidget(btn_bar)

        self.tabs.currentChanged.connect(self._on_tab_changed)

    # =========================================================================
    # PUBLISH TAB — compact 2-column layout
    # =========================================================================

    def _build_publish_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        w = QtWidgets.QWidget()
        scroll.setWidget(w)

        outer = QtWidgets.QVBoxLayout(w)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        # ── ROW 1: Asset Info (left) + LOD div chips (right) ──────────────
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(8)

        # Asset Info card
        asset_card = self._card()
        asset_card.setMinimumWidth(260)
        af = QtWidgets.QFormLayout(asset_card)
        af.setContentsMargins(10, 8, 10, 8)
        af.setSpacing(5)
        af.setLabelAlignment(Qt.AlignRight)

        self.le_asset = QtWidgets.QLineEdit()
        self.le_asset.setPlaceholderText("e.g. rock_boulder_a")
        self.le_asset.textChanged.connect(self._update_preview)

        self.cb_set = QtWidgets.QComboBox()
        self._refresh_sets()
        self.cb_set.currentTextChanged.connect(self._update_preview)

        self.le_new_set = QtWidgets.QLineEdit()
        self.le_new_set.setPlaceholderText("New set name...")
        self.le_new_set.setFixedWidth(110)
        btn_add_set = QtWidgets.QPushButton("+")
        btn_add_set.setFixedWidth(28)
        btn_add_set.clicked.connect(self._add_set)
        set_new_row = QtWidgets.QHBoxLayout()
        set_new_row.addWidget(self.le_new_set)
        set_new_row.addWidget(btn_add_set)

        af.addRow("Asset:", self.le_asset)
        af.addRow("Set:", self.cb_set)
        af.addRow("New Set:", set_new_row)

        lbl_ai = QtWidgets.QLabel("ASSET INFO")
        lbl_ai.setObjectName("sectionTitle")
        lbl_ai.setStyleSheet("background:#3a3a3a;color:#999;font-size:9px;letter-spacing:.5px;"
                             "padding:2px 8px;border-top:1px solid #555;border-bottom:1px solid #1a1a1a;")

        ai_wrap = QtWidgets.QWidget()
        ai_vl = QtWidgets.QVBoxLayout(ai_wrap)
        ai_vl.setContentsMargins(0,0,0,0)
        ai_vl.setSpacing(2)
        ai_vl.addWidget(lbl_ai)
        ai_vl.addWidget(asset_card)
        row1.addWidget(ai_wrap, 3)

        # LOD chips card
        lod_card = self._card()
        lc = QtWidgets.QVBoxLayout(lod_card)
        lc.setContentsMargins(8, 8, 8, 8)
        lc.setSpacing(4)

        chips_h = QtWidgets.QHBoxLayout()
        chips_h.setSpacing(6)
        for lod, cfg in LOD_CONFIG.items():
            chip = QtWidgets.QFrame()
            chip.setStyleSheet("QFrame{background:#2a2a2a;border:1px solid #555;border-radius:3px;}")
            chip.setFixedHeight(54)
            cl2 = QtWidgets.QVBoxLayout(chip)
            cl2.setContentsMargins(10, 3, 10, 3)
            cl2.setSpacing(0)
            lbl_name = QtWidgets.QLabel(lod.upper())
            lbl_name.setAlignment(Qt.AlignCenter)
            lbl_name.setStyleSheet("color:#888;font-size:9px;letter-spacing:1px;")
            lbl_div = QtWidgets.QLabel(str(cfg["div"]))
            lbl_div.setAlignment(Qt.AlignCenter)
            lbl_div.setStyleSheet("color:#7ab8e6;font-size:18px;font-weight:bold;")
            lbl_unit = QtWidgets.QLabel("div")
            lbl_unit.setAlignment(Qt.AlignCenter)
            lbl_unit.setStyleSheet("color:#555;font-size:9px;")
            cl2.addWidget(lbl_name)
            cl2.addWidget(lbl_div)
            cl2.addWidget(lbl_unit)
            chips_h.addWidget(chip)
        lc.addLayout(chips_h)

        self.cb_subdiv = QtWidgets.QComboBox()
        self.cb_subdiv.addItems(SUBDIV_TYPES)
        lc_form = QtWidgets.QFormLayout()
        lc_form.setContentsMargins(0,4,0,0)
        lc_form.setSpacing(4)
        lc_form.setLabelAlignment(Qt.AlignRight)
        lc_form.addRow("Subdiv:", self.cb_subdiv)
        lc.addLayout(lc_form)

        lbl_lod = QtWidgets.QLabel("LOD SETTINGS  (all div=0)")
        lbl_lod.setObjectName("sectionTitle")
        lbl_lod.setStyleSheet("background:#3a3a3a;color:#999;font-size:9px;letter-spacing:.5px;"
                              "padding:2px 8px;border-top:1px solid #555;border-bottom:1px solid #1a1a1a;")
        lod_wrap = QtWidgets.QWidget()
        lod_vl = QtWidgets.QVBoxLayout(lod_wrap)
        lod_vl.setContentsMargins(0,0,0,0)
        lod_vl.setSpacing(2)
        lod_vl.addWidget(lbl_lod)
        lod_vl.addWidget(lod_card)
        row1.addWidget(lod_wrap, 2)

        outer.addLayout(row1)

        # ── ROW 2: Suffixes (left) + Export Formats (right) ───────────────
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(8)

        # Suffixes
        sfx_card = self._card()
        sf = QtWidgets.QFormLayout(sfx_card)
        sf.setContentsMargins(10, 8, 10, 8)
        sf.setSpacing(5)
        sf.setLabelAlignment(Qt.AlignRight)
        self.le_sfx_hi  = QtWidgets.QLineEdit("_hi");  self.le_sfx_hi.setFixedWidth(65)
        self.le_sfx_mid = QtWidgets.QLineEdit("_mid"); self.le_sfx_mid.setFixedWidth(65)
        self.le_sfx_lo  = QtWidgets.QLineEdit("_lo");  self.le_sfx_lo.setFixedWidth(65)
        sf.addRow("Hi:", self.le_sfx_hi)
        sf.addRow("Mid:", self.le_sfx_mid)
        sf.addRow("Lo:", self.le_sfx_lo)

        lbl_sfx = QtWidgets.QLabel("LOD SUFFIXES")
        lbl_sfx.setStyleSheet("background:#3a3a3a;color:#999;font-size:9px;letter-spacing:.5px;"
                              "padding:2px 8px;border-top:1px solid #555;border-bottom:1px solid #1a1a1a;")
        sfx_wrap = QtWidgets.QWidget()
        sfx_vl = QtWidgets.QVBoxLayout(sfx_wrap)
        sfx_vl.setContentsMargins(0,0,0,0); sfx_vl.setSpacing(2)
        sfx_vl.addWidget(lbl_sfx); sfx_vl.addWidget(sfx_card)
        row2.addWidget(sfx_wrap, 1)

        # Export formats + ABC range
        fmt_card = self._card()
        fmt_vl = QtWidgets.QVBoxLayout(fmt_card)
        fmt_vl.setContentsMargins(10, 8, 10, 8)
        fmt_vl.setSpacing(4)
        self.chk_ma  = QtWidgets.QCheckBox("Maya ASCII  (.ma)")
        self.chk_ass = QtWidgets.QCheckBox("Arnold ASS  (.ass)")
        self.chk_abc = QtWidgets.QCheckBox("Alembic/GPU  (.abc)")
        for chk in (self.chk_ma, self.chk_ass, self.chk_abc):
            chk.setChecked(True)
            chk.stateChanged.connect(self._update_preview)
            fmt_vl.addWidget(chk)

        # ABC frame range inline
        fr_h = QtWidgets.QHBoxLayout()
        fr_h.setSpacing(4)
        fr_h.addWidget(QtWidgets.QLabel("Frames:"))
        self.pub_le_fs = QtWidgets.QLineEdit("1"); self.pub_le_fs.setFixedWidth(40)
        self.pub_le_fe = QtWidgets.QLineEdit("1"); self.pub_le_fe.setFixedWidth(40)
        fr_h.addWidget(self.pub_le_fs)
        fr_h.addWidget(QtWidgets.QLabel("–"))
        fr_h.addWidget(self.pub_le_fe)
        fr_h.addStretch()
        fmt_vl.addLayout(fr_h)

        self.pub_le_abc_flags = QtWidgets.QLineEdit("-uvWrite -worldSpace -writeVisibility")
        self.pub_le_abc_flags.setStyleSheet("font-family:Consolas,monospace;font-size:10px;")
        fmt_fl = QtWidgets.QFormLayout()
        fmt_fl.setContentsMargins(0,2,0,0)
        fmt_fl.setSpacing(3)
        fmt_fl.setLabelAlignment(Qt.AlignRight)
        fmt_fl.addRow("ABC flags:", self.pub_le_abc_flags)
        fmt_vl.addLayout(fmt_fl)

        lbl_fmt = QtWidgets.QLabel("EXPORT FORMATS")
        lbl_fmt.setStyleSheet("background:#3a3a3a;color:#999;font-size:9px;letter-spacing:.5px;"
                              "padding:2px 8px;border-top:1px solid #555;border-bottom:1px solid #1a1a1a;")
        fmt_wrap = QtWidgets.QWidget()
        fmt_wl = QtWidgets.QVBoxLayout(fmt_wrap)
        fmt_wl.setContentsMargins(0,0,0,0); fmt_wl.setSpacing(2)
        fmt_wl.addWidget(lbl_fmt); fmt_wl.addWidget(fmt_card)
        row2.addWidget(fmt_wrap, 2)

        outer.addLayout(row2)

        # ── Path Preview ───────────────────────────────────────────────────
        lbl_prev = QtWidgets.QLabel("OUTPUT PATH PREVIEW")
        lbl_prev.setStyleSheet("background:#3a3a3a;color:#999;font-size:9px;letter-spacing:.5px;"
                               "padding:2px 8px;border-top:1px solid #555;border-bottom:1px solid #1a1a1a;")
        outer.addWidget(lbl_prev)
        self.te_preview = QtWidgets.QPlainTextEdit()
        self.te_preview.setReadOnly(True)
        self.te_preview.setFixedHeight(88)
        self.te_preview.setStyleSheet(
            "background:#151515;color:#7a9f6a;font-family:Consolas,monospace;"
            "font-size:10px;border:1px solid #333;")
        outer.addWidget(self.te_preview)

        # ── Publish Log ────────────────────────────────────────────────────
        lbl_log = QtWidgets.QLabel("PUBLISH LOG")
        lbl_log.setStyleSheet("background:#3a3a3a;color:#999;font-size:9px;letter-spacing:.5px;"
                              "padding:2px 8px;border-top:1px solid #555;border-bottom:1px solid #1a1a1a;")
        outer.addWidget(lbl_log)
        self.te_pub_log = self._log_widget(120)
        outer.addWidget(self.te_pub_log)
        outer.addStretch()

        self._update_preview()
        return scroll

    # =========================================================================
    # FILE CONVERTER TAB — scene-query based workflow
    # =========================================================================

    def _build_converter_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        w = QtWidgets.QWidget()
        scroll.setWidget(w)
        layout = QtWidgets.QVBoxLayout(w)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── Step 1: Query selected node ────────────────────────────────────
        layout.addWidget(self._slabel("STEP 1 — SELECT NODE IN MAYA & QUERY"))

        query_card = self._card()
        query_vl = QtWidgets.QVBoxLayout(query_card)
        query_vl.setContentsMargins(10, 10, 10, 10)
        query_vl.setSpacing(6)

        hint = QtWidgets.QLabel(
            "Select any group, GPU cache node, or ASS standin in the outliner,\n"
            "then click Query. The tool reads the file path from the node's attribute\n"
            "and derives all LOD publish paths from the pipeline structure."
        )
        hint.setStyleSheet("color:#888; font-size:10px;")
        query_vl.addWidget(hint)

        btn_query = QtWidgets.QPushButton("⟳  Query Selected Node")
        btn_query.setObjectName("btnQuery")
        btn_query.setFixedHeight(30)
        btn_query.clicked.connect(self._on_query_node)
        query_vl.addWidget(btn_query)

        layout.addWidget(query_card)

        # ── Queried info display ───────────────────────────────────────────
        layout.addWidget(self._slabel("QUERIED ASSET INFO"))

        info_card = QtWidgets.QFrame()
        info_card.setObjectName("infoCard")
        info_vl = QtWidgets.QVBoxLayout(info_card)
        info_vl.setContentsMargins(10, 8, 10, 8)
        info_vl.setSpacing(3)

        self.lbl_qi_node   = self._info_label("Node:", "—")
        self.lbl_qi_set    = self._info_label("Set:", "—")
        self.lbl_qi_asset  = self._info_label("Asset:", "—")
        self.lbl_qi_lod    = self._info_label("Detected LOD:", "—")
        self.lbl_qi_path   = self._info_label("Source Path:", "—")
        self.lbl_qi_xform  = self._info_label("World Pos:", "—")

        for row in (self.lbl_qi_node, self.lbl_qi_set, self.lbl_qi_asset,
                    self.lbl_qi_lod, self.lbl_qi_path, self.lbl_qi_xform):
            info_vl.addLayout(row["layout"])

        layout.addWidget(info_card)

        # ── Step 2: Operations ────────────────────────────────────────────
        layout.addWidget(self._slabel("STEP 2 — CHOOSE OPERATION"))

        ops_card = self._card()
        ops_vl = QtWidgets.QVBoxLayout(ops_card)
        ops_vl.setContentsMargins(10, 10, 10, 10)
        ops_vl.setSpacing(8)

        # ── OP A: ABC → ASS ──────────────────────────────────────────────
        op_a = self._op_card(
            "ABC  →  ASS",
            "GPU cache (.abc) file for the queried LOD already exists.\n"
            "Converts it to Arnold Scene Source (.ass) in the same publish folder.\n"
            "Position is stored and re-applied to the replaced node.",
            "#2a4060"
        )
        self.btn_abc_to_ass = QtWidgets.QPushButton("Convert ABC → ASS")
        self.btn_abc_to_ass.setObjectName("btnAction")
        self.btn_abc_to_ass.clicked.connect(self._on_abc_to_ass)
        op_a.addWidget(self.btn_abc_to_ass)
        ops_vl.addLayout(op_a)

        # ── OP B: ASS → ABC ──────────────────────────────────────────────
        op_b = self._op_card(
            "ASS  →  ABC  (GPU)",
            "Arnold standin (.ass) for the queried LOD already exists.\n"
            "Converts it to GPU cache Alembic (.abc) in the same publish folder.\n"
            "Position is stored and re-applied to the replaced node.",
            "#2a4060"
        )
        self.btn_ass_to_abc = QtWidgets.QPushButton("Convert ASS → ABC")
        self.btn_ass_to_abc.setObjectName("btnAction")
        self.btn_ass_to_abc.clicked.connect(self._on_ass_to_abc)
        op_b.addWidget(self.btn_ass_to_abc)
        ops_vl.addLayout(op_b)

        # Separator
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color:#444;")
        ops_vl.addWidget(sep)

        # ── OP C: ASS → Import .ma ────────────────────────────────────────
        op_c = self._op_card(
            "ASS  →  Import Maya File  (.ma)",
            "Finds the latest work .ma file derived from the publish path:\n"
            "  sets/<set>/publish/elements/<asset>/mod/work/<latest_ver>/<file>.ma\n"
            "Imports it into the scene, matches transform, replaces the ASS node.",
            "#3a2a10"
        )
        self.btn_ass_to_ma = QtWidgets.QPushButton("Import .ma from work path")
        self.btn_ass_to_ma.setObjectName("btnWarn")
        self.btn_ass_to_ma.clicked.connect(self._on_ass_to_ma)
        op_c.addWidget(self.btn_ass_to_ma)
        ops_vl.addLayout(op_c)

        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setStyleSheet("color:#444;")
        ops_vl.addWidget(sep2)

        # ── OP D: Selected hi/mid/lo groups → Overwrite publish ──────────
        op_d_outer = QtWidgets.QVBoxLayout()
        op_d_lbl = QtWidgets.QLabel("MAYA GROUPS  →  OVERWRITE PUBLISH  (hi / mid / lo)")
        op_d_lbl.setStyleSheet("color:#e6c23e; font-weight:bold; font-size:11px;")
        op_d_outer.addWidget(op_d_lbl)

        op_d_desc = QtWidgets.QLabel(
            "After editing the imported .ma, select the three LOD groups in the scene\n"
            "(matching _hi / _mid / _lo suffixes from Publish tab settings).\n"
            "Set & Asset names are inferred from the queried path — no manual entry needed.\n"
            "Overwrites existing publish files (ma, ass, abc) for all three LODs."
        )
        op_d_desc.setStyleSheet("color:#888; font-size:10px;")
        op_d_outer.addWidget(op_d_desc)

        # Format checkboxes for overwrite
        fmt_row = QtWidgets.QHBoxLayout()
        self.chk_ow_ma  = QtWidgets.QCheckBox(".ma");  self.chk_ow_ma.setChecked(True)
        self.chk_ow_ass = QtWidgets.QCheckBox(".ass"); self.chk_ow_ass.setChecked(True)
        self.chk_ow_abc = QtWidgets.QCheckBox(".abc"); self.chk_ow_abc.setChecked(True)
        for c in (self.chk_ow_ma, self.chk_ow_ass, self.chk_ow_abc):
            fmt_row.addWidget(c)
        fmt_row.addStretch()
        op_d_outer.addLayout(fmt_row)

        self.btn_overwrite = QtWidgets.QPushButton("▶  Overwrite Publish from Selected Groups")
        self.btn_overwrite.setObjectName("btnPublish")
        self.btn_overwrite.setFixedHeight(30)
        self.btn_overwrite.setStyleSheet(
            "QPushButton { background:#c05020; color:#fff; font-weight:bold;"
            " border:1px solid #e07040; padding:5px 16px; }"
            "QPushButton:hover { background:#d06030; }"
            "QPushButton:pressed { background:#a04010; }"
        )
        self.btn_overwrite.clicked.connect(self._on_overwrite_publish)
        op_d_outer.addWidget(self.btn_overwrite)

        ops_vl.addLayout(op_d_outer)
        layout.addWidget(ops_card)

        # ── Conversion Log ────────────────────────────────────────────────
        layout.addWidget(self._slabel("CONVERSION LOG"))
        self.te_conv_log = self._log_widget(130)
        layout.addWidget(self.te_conv_log)
        layout.addStretch()

        return scroll

    # =========================================================================
    # CONVERTER LOGIC
    # =========================================================================

    def _on_query_node(self):
        """Read selected node, parse publish path, populate info panel."""
        path, node = _query_selected_publish_path()

        if not path:
            self._clog("ERROR: No publish file path found on selected node.\n"
                       "       Select a GPU cache or ASS standin node.", "err")
            self._queried_info = None
            return

        info = _parse_publish_path(path)
        if not info:
            self._clog("ERROR: Path does not match pipeline structure:\n  {}".format(path), "err")
            self._queried_info = None
            return

        self._queried_info = info
        self._queried_node = node
        self._queried_xform = _get_node_world_matrix(node) if node else None

        # Update info labels
        self.lbl_qi_node["val"].setText(node or "—")
        self.lbl_qi_set["val"].setText(info["set"])
        self.lbl_qi_asset["val"].setText(info["asset"])
        self.lbl_qi_lod["val"].setText(info["lod"].upper())
        self.lbl_qi_path["val"].setText(path)
        if self._queried_xform:
            t = self._queried_xform["t"]
            self.lbl_qi_xform["val"].setText(
                "T({:.2f}, {:.2f}, {:.2f})".format(t[0], t[1], t[2])
            )

        self._clog("Queried: {} — set={} asset={} lod={}".format(
            node, info["set"], info["asset"], info["lod"].upper()), "ok")

    def _on_abc_to_ass(self):
        info = self._queried_info
        if not info:
            self._clog("ERROR: Query a node first (Step 1).", "err"); return

        abc_paths = _lod_paths_from_info(info, "abc")
        ass_paths = _lod_paths_from_info(info, "ass")
        lod = info["lod"]

        abc_src = abc_paths[lod]
        ass_dst = ass_paths[lod]

        if not os.path.isfile(abc_src):
            self._clog("ERROR: ABC file not found:\n  {}".format(abc_src), "err"); return

        self._clog("ABC → ASS: {}".format(os.path.basename(abc_src)), "info")
        self._clog("  src: {}".format(abc_src))
        self._clog("  dst: {}".format(ass_dst))

        try:
            # Convert ABC→MA temp, then MA→ASS via kick or direct ASS export
            # Since we're in Maya session: import ABC, export ASS, remove namespace
            ns = "_dng_abc_ass_tmp_"
            new_nodes = cmds.file(abc_src, i=True, namespace=ns, returnNewNodes=True) or []
            top = [n for n in cmds.ls("{}:*".format(ns), assemblies=True) or []]

            if top:
                cmds.select(top)
                os.makedirs(os.path.dirname(ass_dst), exist_ok=True)
                cmds.arnoldExportAss(
                    f=ass_dst,
                    root=top[0] if len(top) == 1 else top,
                    selected=False, shadowLinks=1, lightLinks=1, boundingBox=True,
                    startFrame=1, endFrame=1,
                )
                self._clog("ASS written: {}".format(os.path.basename(ass_dst)), "ok")
            else:
                self._clog("WARNING: No top nodes found after ABC import.", "warn")

            try:
                cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
            except Exception:
                pass

        except Exception as e:
            self._clog("ERROR ABC→ASS: {}".format(e), "err")

    def _on_ass_to_abc(self):
        info = self._queried_info
        if not info:
            self._clog("ERROR: Query a node first (Step 1).", "err"); return

        ass_paths = _lod_paths_from_info(info, "ass")
        abc_paths = _lod_paths_from_info(info, "abc")
        lod = info["lod"]

        ass_src = ass_paths[lod]
        abc_dst = abc_paths[lod]

        if not os.path.isfile(ass_src):
            self._clog("ERROR: ASS file not found:\n  {}".format(ass_src), "err"); return

        self._clog("ASS → ABC: {}".format(os.path.basename(ass_src)), "info")
        self._clog("  src: {}".format(ass_src))
        self._clog("  dst: {}".format(abc_dst))

        try:
            # Import ASS into scene, export as GPU cache (abc), then clean up
            if not cmds.pluginInfo("mtoa", query=True, loaded=True):
                cmds.loadPlugin("mtoa")
            try:
                import mtoa.core; mtoa.core.createOptions()
            except Exception:
                pass

            ns = "_dng_ass_abc_tmp_"
            cmds.arnoldImportAss(f=ass_src, namespace=ns)
            top = cmds.ls("{}:*".format(ns), assemblies=True) or []

            if top:
                os.makedirs(os.path.dirname(abc_dst), exist_ok=True)
                export_dir = os.path.dirname(abc_dst)
                abc_name = os.path.splitext(os.path.basename(abc_dst))[0]
                cmds.gpuCache(
                    top[0],
                    startTime=1, endTime=1,
                    optimizationThreshold=40000,
                    dataFormat="ogawa",
                    directory=export_dir,
                    fileName=abc_name,
                )
                self._clog("ABC written: {}".format(os.path.basename(abc_dst)), "ok")
            else:
                self._clog("WARNING: No top nodes found after ASS import.", "warn")

            try:
                cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
            except Exception:
                pass

        except Exception as e:
            self._clog("ERROR ASS→ABC: {}".format(e), "err")

    def _on_ass_to_ma(self):
        """Find latest work .ma and import it, replacing the queried ASS node."""
        info = self._queried_info
        if not info:
            self._clog("ERROR: Query a node first (Step 1).", "err"); return

        ma_path, work_root, ver = _work_ma_path_from_info(info)

        self._clog("ASS → Import .ma", "info")
        self._clog("  work version: {}".format(ver))
        self._clog("  ma path: {}".format(ma_path))

        if not os.path.isfile(ma_path):
            self._clog("ERROR: Work .ma not found:\n  {}".format(ma_path), "err")
            self._clog("  (Publish a work version first via the Publish tab)", "warn")
            return


        try:
            node = self._queried_node
            xform = self._queried_xform

            # ------------------------------------------------------------
            # IMPORT MA
            # ------------------------------------------------------------
            new_nodes = cmds.file(
                ma_path,
                i=True,
                returnNewNodes=True
            ) or []

            imported_tops = [
                n for n in new_nodes
                if _is_node_type(n, "transform") and not _first_parent(n)
            ]

            if not imported_tops:
                imported_tops = [
                    n for n in new_nodes
                    if _is_node_type(n, "transform")
                ]

            if not imported_tops:
                self._clog("WARNING: No top transforms in imported .ma", "warn")
                return

            # ------------------------------------------------------------
            # PLACE IMPORTED CONTENT
            # ------------------------------------------------------------
            if xform:
                for top in imported_tops:
                    _apply_world_matrix(top, xform)

            # ------------------------------------------------------------
            # DELETE ORIGINAL ASS GROUP
            # ------------------------------------------------------------
            if node and cmds.objExists(node):
                # delete full hierarchy/content
                cmds.delete(node)

                self._clog(
                    "Removed original ASS group: {}".format(node),
                    "info"
                )

            cmds.select(cl=True)

            self._clog(
                ".ma imported and replaced successfully: {}".format(
                    os.path.basename(ma_path)
                ),
                "ok"
            )

        except Exception as e:
            self._clog("ERROR importing .ma: {}".format(e), "err")

    def _on_overwrite_publish(self):
        """
        From the current scene, detect hi/mid/lo groups using publish tab suffix settings,
        overwrite all publish LOD files inferred from queried path info.
        No work file save — directly overwrite publish folder.
        """
        info = self._queried_info
        if not info:
            self._clog("ERROR: Query a node first (Step 1).", "err"); return

        sfx_map = self._sfx_map()
        lod_groups = _get_lod_groups(sfx_map)
        subdiv_type = self.cb_subdiv.currentText()

        want_ma  = self.chk_ow_ma.isChecked()
        want_ass = self.chk_ow_ass.isChecked()
        want_abc = self.chk_ow_abc.isChecked()

        self._clog("=== Overwrite Publish: {} / {} ===".format(info["set"], info["asset"]), "info")
        self._clog("    Formats: {} {} {}".format(
            ".ma" if want_ma else "", ".ass" if want_ass else "", ".abc" if want_abc else ""), "info")

        for lod, cfg in LOD_CONFIG.items():
            groups = lod_groups.get(lod, [])
            if not groups:
                self._clog("SKIP {}: no groups with suffix '{}'".format(lod, sfx_map[lod]), "warn")
                continue

            # Build publish paths from info
            ma_paths  = _lod_paths_from_info(info, "ma")
            ass_paths = _lod_paths_from_info(info, "ass")
            abc_paths = _lod_paths_from_info(info, "abc")

            ma_out  = ma_paths[lod]
            ass_out = ass_paths[lod]
            abc_out = abc_paths[lod]

            self._clog("Processing {} — groups: {}".format(lod.upper(), ", ".join(groups)), "info")

            try:
                ok = _smooth_duplicate_and_export(
                    groups=groups,
                    div_level=cfg["div"],
                    subdiv_type=subdiv_type,
                    ma_path=ma_out   if want_ma  else None,
                    ass_path=ass_out if want_ass else None,
                    abc_path=abc_out if want_abc else None,
                    frame_range=(1, 1),
                    abc_flags=self.pub_le_abc_flags.text().strip(),
                    asset_name=info["asset"],
                )
                if ok:
                    if want_ma:
                        self._clog("  MA  ✓  {}".format(os.path.basename(ma_out)), "ok")
                    if want_ass:
                        self._clog("  ASS ✓  {}".format(os.path.basename(ass_out)), "ok")
                    if want_abc:
                        self._clog("  ABC ✓  {}".format(os.path.basename(abc_out)), "ok")
                else:
                    self._clog("  WARNING: No geometry found in {} groups.".format(lod), "warn")
            except Exception as e:
                self._clog("  ERROR [{}]: {}".format(lod, e), "err")

        self._clog("=== Overwrite complete ===", "info")

    # =========================================================================
    # PUBLISH TAB LOGIC
    # =========================================================================

    def _sfx_map(self):
        return {
            "hi":  self.le_sfx_hi.text().strip()  or "_hi",
            "mid": self.le_sfx_mid.text().strip() or "_mid",
            "lo":  self.le_sfx_lo.text().strip()  or "_lo",
        }

    def _refresh_sets(self):
        self.cb_set.clear()
        sets = _get_available_sets(PROJECT_ROOT_DEFAULT)
        self.cb_set.addItems(sets)

    def _add_set(self):
        name = self.le_new_set.text().strip()
        if not name:
            return
        self.cb_set.addItem(name)
        self.cb_set.setCurrentText(name)
        self.le_new_set.clear()

    def _update_preview(self):
        asset = self.le_asset.text().strip()
        set_name = self.cb_set.currentText().strip()
        root = PROJECT_ROOT_DEFAULT
        if not asset or not set_name:
            self.te_preview.setPlainText("Enter asset + set...")
            return
        work_root = os.path.join(root, set_name, "publish", "elements", asset, "mod", "work")
        version = _next_work_version(work_root)
        lines = ["SET: {}    VER: {}".format(set_name, version), ""]
        for lod in ("hi", "mid", "lo"):
            p = _build_paths(root, set_name, asset, lod, version)
            parts = []
            if self.chk_ma.isChecked():  parts.append(".ma")
            if self.chk_ass.isChecked(): parts.append(".ass")
            if self.chk_abc.isChecked(): parts.append(".abc")
            lines.append("[{}]  {}  ({})".format(lod.upper(), p["stem"], " ".join(parts)))
            lines.append("  " + p["publish_dir"])
        self.te_preview.setPlainText("\n".join(lines))

    def _on_validate(self):
        self._plog("Scanning scene groups...", "info")
        sfx_map = self._sfx_map()
        lod_groups = _get_lod_groups(sfx_map)
        found_any = False
        for lod, grps in lod_groups.items():
            if grps:
                for g in grps:
                    self._plog("Found: {} → {}/".format(g, lod), "ok")
                found_any = True
            else:
                self._plog("No groups with suffix '{}'".format(sfx_map[lod]), "warn")
        if found_any:
            self._plog("Validation complete — scene looks good", "info")
        else:
            self._plog("No LOD groups detected. Check suffix settings.", "err")

    def _on_publish(self):
        asset = self.le_asset.text().strip()
        if not asset:
            self._plog("ERROR: Asset name is required", "err"); return

        root = PROJECT_ROOT_DEFAULT
        set_name = self.cb_set.currentText().strip()
        if not set_name:
            self._plog("ERROR: Set required", "err"); return

        work_root = os.path.join(root, set_name, "publish", "elements", asset, "mod", "work")
        version = _next_work_version(work_root)
        sfx_map = self._sfx_map()
        lod_groups = _get_lod_groups(sfx_map)
        subdiv_type = self.cb_subdiv.currentText()

        try:
            fs = int(self.pub_le_fs.text() or "1")
            fe = int(self.pub_le_fe.text() or "1")
        except ValueError:
            fs, fe = 1, 1
        abc_flags = self.pub_le_abc_flags.text().strip()

        self._plog("=== Publish: dng_{} {} ===".format(asset, version), "info")

        master_paths = _build_paths(root, set_name, asset, "hi", version)
        os.makedirs(master_paths["work_dir"], exist_ok=True)
        cmds.file(rename=master_paths["work_ma"])
        cmds.file(save=True, type="mayaAscii")
        self._plog("MASTER saved: {}".format(os.path.basename(master_paths["work_ma"])), "ok")

        for lod, cfg in LOD_CONFIG.items():
            groups = lod_groups.get(lod, [])
            paths = _build_paths(root, set_name, asset, lod, version)
            div = cfg["div"]

            if not groups:
                self._plog("SKIP {}: no groups with suffix '{}'".format(lod, sfx_map[lod]), "warn")
                continue

            want_ma  = self.chk_ma.isChecked()
            want_ass = self.chk_ass.isChecked()
            want_abc = self.chk_abc.isChecked()

            self._plog("Processing {} ({}div) — {}".format(lod.upper(), div, ", ".join(groups)), "info")

            try:
                ok = _smooth_duplicate_and_export(
                    groups=groups, div_level=div, subdiv_type=subdiv_type,
                    ma_path=paths["ma"]   if want_ma  else None,
                    ass_path=paths["ass"] if want_ass else None,
                    abc_path=paths["abc"] if want_abc else None,
                    frame_range=(fs, fe), abc_flags=abc_flags, asset_name=asset,
                )
                if ok:
                    if want_ma:  self._plog("MA  ✓  {}".format(os.path.basename(paths["ma"])), "ok")
                    if want_ass: self._plog("ASS ✓  {}".format(os.path.basename(paths["ass"])), "ok")
                    if want_abc: self._plog("ABC ✓  {}".format(os.path.basename(paths["abc"])), "ok")
                else:
                    self._plog("WARNING: No geo found in {} groups".format(lod), "warn")
            except Exception as e:
                self._plog("ERROR [{}]: {}".format(lod, e), "err")

        self._plog("=== Publish complete ===", "info")

    # =========================================================================
    # SHARED UI HELPERS
    # =========================================================================

    def _slabel(self, text):
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet("background:#3a3a3a;color:#999;font-size:9px;letter-spacing:.5px;"
                          "padding:2px 8px;border-top:1px solid #555;border-bottom:1px solid #1a1a1a;")
        return lbl

    def _card(self):
        f = QtWidgets.QFrame()
        f.setObjectName("card")
        return f

    def _log_widget(self, height=90):
        te = QtWidgets.QPlainTextEdit()
        te.setReadOnly(True)
        te.setFixedHeight(height)
        te.setStyleSheet("background:#151515;color:#7a9f6a;font-family:Consolas,monospace;"
                         "font-size:10px;border:1px solid #333;")
        return te

    def _info_label(self, label_text, val_text):
        """Return a dict with a QHBoxLayout, label widget, and value widget."""
        h = QtWidgets.QHBoxLayout()
        h.setSpacing(6)
        lbl = QtWidgets.QLabel(label_text)
        lbl.setStyleSheet("color:#666; font-size:10px; min-width:90px;")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val = QtWidgets.QLabel(val_text)
        val.setStyleSheet("color:#9fc860; font-size:10px; font-family:Consolas,monospace;")
        val.setWordWrap(True)
        h.addWidget(lbl)
        h.addWidget(val, 1)
        return {"layout": h, "val": val}

    def _op_card(self, title, desc, bg_color="#353535"):
        outer = QtWidgets.QVBoxLayout()
        frame = QtWidgets.QFrame()
        frame.setStyleSheet("QFrame{{background:{};border:1px solid #555;border-radius:3px;}}".format(bg_color))
        vl = QtWidgets.QVBoxLayout(frame)
        vl.setContentsMargins(10, 8, 10, 8)
        vl.setSpacing(4)
        lbl_t = QtWidgets.QLabel(title)
        lbl_t.setStyleSheet("color:#7ab8e6; font-weight:bold; font-size:11px;")
        lbl_d = QtWidgets.QLabel(desc)
        lbl_d.setStyleSheet("color:#777; font-size:10px;")
        lbl_d.setWordWrap(True)
        vl.addWidget(lbl_t)
        vl.addWidget(lbl_d)
        outer.addWidget(frame)
        # return inner layout so caller can addWidget to the frame's vl
        # We return a proxy that adds to vl
        outer._target_vl = vl
        outer.addWidget = vl.addWidget  # type: ignore
        return outer

    def _plog(self, msg, kind="info"):
        self._write_log(msg, kind, self.te_pub_log)

    def _clog(self, msg, kind="info"):
        self._write_log(msg, kind, self.te_conv_log)

    def _write_log(self, msg, kind, target):
        colors = {"info": "#7ab8e6", "warn": "#e6c23e", "err": "#e05050", "ok": "#7a9f6a"}
        color = colors.get(kind, "#7a9f6a")
        html = '<span style="color:{c}">&gt; {m}</span>'.format(
            c=color, m=msg.replace("<", "&lt;").replace(">", "&gt;"))
        target.appendHtml(html)
        QtWidgets.QApplication.processEvents()

    def _clear_log(self):
        if self.tabs.currentIndex() == 0:
            self.te_pub_log.clear()
        else:
            self.te_conv_log.clear()

    def _on_tab_changed(self, idx):
        self.btn_publish.setVisible(idx == 0)
        self.btn_validate.setVisible(idx == 0)


# ---------------------------------------------------------------------------
# Maya-aware launch
# ---------------------------------------------------------------------------

_WINDOW_INSTANCE = None


def show():
    global _WINDOW_INSTANCE
    if _WINDOW_INSTANCE is not None:
        try:
            _WINDOW_INSTANCE.close()
            _WINDOW_INSTANCE.deleteLater()
        except Exception:
            pass
    try:
        import maya.OpenMayaUI as omui
        from shiboken2 import wrapInstance
        ptr = omui.MQtUtil.mainWindow()
        parent = wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        parent = None
    _WINDOW_INSTANCE = DNGPublisher(parent)
    _WINDOW_INSTANCE.show()
    _WINDOW_INSTANCE.raise_()
    return _WINDOW_INSTANCE


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = DNGPublisher()
    win.show()
    sys.exit(app.exec_())