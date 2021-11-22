#
#  M E L O N R I P P E R
#

bl_info = {
    "name": "MelonRipper NDS Dumps",
    "author": "scurest",
    "version": (1, 0, 0),
    "blender": (2, 82, 0),
    "location": "File > Import",
    "description": "Import scenes ripped from Nintendo DS with melonDS + MelonRipper",
    "doc_url": "https://github.com/scurest/MelonRipper",
    "category": "Import",
}

import bpy
import struct
import time

from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper


class ShowErrorMsg(RuntimeError): pass  # raise to show an error message

class ImportMelonRip(bpy.types.Operator, ImportHelper):
    """Load a Nintendo DS rip from melonDS + MelonRipper"""
    bl_idname = "import_model.melon_rip"
    bl_label = "Import MelonRipper NDS Dump"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".dump"
    filter_glob: StringProperty(
        default="*.dump;",
        options={'HIDDEN'},
    )

    def execute(self, context):
        start_t = time.time()

        with open(self.filepath, 'rb') as f:
            dump = f.read()
        rip = Rip(dump)

        try:
            import_rip(rip)
        except ShowErrorMsg as e:
            self.report({'ERROR'}, e.args[0])
            return {'CANCELLED'}

        end_t = time.time()
        print('Finished in %.1f s' % (end_t - start_t))
        return {'FINISHED'}

def menu_func_import(self, context):
    self.layout.operator(ImportMelonRip.bl_idname, text="MelonRipper NDS Dump")

def register():
    bpy.utils.register_class(ImportMelonRip)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ImportMelonRip)


class Rip:
    def __init__(self, dump):
        self.dump = dump
        self.material_cache = {}
        self.texture_cache = {}
        self.toon_table_texture = None


def check_magic(rip):
    magic = rip.dump[:24]
    magic = magic.rstrip(b'\0')
    prefix = b'melon ripper v'
    if not magic.startswith(prefix):
        raise ShowErrorMsg('Not a MelonRipper file')

    rest = magic[len(prefix):]
    try:
        version = int(str(rest, encoding='ascii'))
    except ValueError:
        raise ShowErrorMsg('Weird magic in MelonRipper file')

    min_version = 1
    max_version = 2
    if version < min_version:
        raise ShowErrorMsg(
            'MelonRipper file too old; '
            'version is %d; must be at least %d' % (version, min_version))
    if version > max_version:
        raise ShowErrorMsg(
            'MelonRipper file too new; '
            'version is %d; I only support %d' % (version, max_version)
        )


def import_rip(rip):
    check_magic(rip)
    pos = 24  # end of magic

    verts = []
    faces = []
    colors = []
    uvs = []
    face_matidxs = []
    material_keys = {}

    texparam = 0
    texpal = 0
    polygon_attr = 0
    blendmode = 0
    texture_width = 8
    texture_height = 8

    dump = rip.dump
    while pos < len(dump):
        op = dump[pos:pos+4]
        pos += 4

        if op in [b"TRI ", b"QUAD"]:
            nverts = 3 if op == b"TRI " else 4

            if (polygon_attr>>4) & 3 == 3:
                # Skip shadow volumes; no idea what to do with these
                pos += (4*3 + 4*3 + 2*2)*nverts
                continue

            vert_index = len(verts)
            for _ in range(nverts):
                x, y, z = struct.unpack_from('<3i', dump, offset=pos)
                pos += 4*3
                x *= 2**-12 ; y *= 2**-12 ; z *= 2**-12  # fixed point to float
                verts.append((x, -z, y))  # everyone seems to use Yup, so Yup2Zup

                r, g, b = struct.unpack_from('<3i', dump, offset=pos)
                pos += 4*3
                # get back to 0-31 range (undo melonDS transform)
                r = (r - 0xFFF) >> 12
                g = (g - 0xFFF) >> 12
                b = (b - 0xFFF) >> 12
                colors += [r, g, b]
                colors.append(blendmode == 2)  # remember for later

                s, t = struct.unpack_from('<2h', dump, offset=pos)
                pos += 2*2
                # Textures are upside down in Blender, so we flip them,
                # but that means we need to flip the T coord too.
                uvs += [s/16/texture_width, 1.0 - t/16/texture_height]

            faces.append(tuple(range(vert_index, vert_index + nverts)))

            material_key = (texparam, texpal, polygon_attr)
            material_index = material_keys.setdefault(material_key, len(material_keys))
            face_matidxs.append(material_index)

        elif op == b"TPRM":
            texparam, = struct.unpack_from('<I', dump, offset=pos)
            pos += 4
            texture_width = 8 << ((texparam >> 20) & 7)
            texture_height = 8 << ((texparam >> 23) & 7)

        elif op == b"TPLT":
            texpal, = struct.unpack_from('<I', dump, offset=pos)
            pos += 4

        elif op == b"PATR":
            polygon_attr, = struct.unpack_from('<I', dump, offset=pos)
            blendmode = (polygon_attr >> 4) & 3
            pos += 4

        elif op == b"VRAM":
            rip.vram_map_texture = struct.unpack_from('<4I', dump, offset=pos)
            pos += 4*4
            rip.vram_map_texpal = struct.unpack_from('<8I', dump, offset=pos)
            pos += 4*8

            banks = []
            # Banks A-D, 128K each
            for i in range(4):
                banks.append(dump[pos : pos + (128 << 10)])
                pos += 128 << 10
            # Banks E-G, E is 64K, F-G are 16K
            for i in range(6):
                banks.append(dump[pos : pos + (16 << 10)])
                pos += 16 << 10

            load_vram(rip, banks)

        elif op == b"DISP":
            rip.disp_cnt, = struct.unpack_from('<I', dump, offset=pos)
            pos += 4

        elif op == b"TOON":
            rip.toon_table = struct.unpack_from('<32H', dump, offset=pos)
            pos += 2*32

        else:
            assert False, "bug: unknown packet"

    backwards_compat(rip)

    mesh = bpy.data.meshes.new('Melon Rip')
    mesh.from_pydata(verts, [], faces)

    colors = convert_vertex_colors(rip, colors)
    color_layer = mesh.vertex_colors.new()
    color_layer.data.foreach_set('color', colors)

    uv_layer = mesh.uv_layers.new()
    uv_layer.data.foreach_set('uv', uvs)

    mesh.polygons.foreach_set('material_index', face_matidxs)

    mesh.validate()

    for material_key in material_keys:
        mat = get_material(rip, *material_key)
        mesh.materials.append(mat)

    ob = bpy.data.objects.new('Melon Rip', mesh)
    bpy.context.scene.collection.objects.link(ob)

    if bpy.ops.object.select_all.poll():
        bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def load_vram(rip, banks):
    vram_tex = bytearray()
    vram_pal = bytearray()

    for i in range(4):
        mask = rip.vram_map_texture[i]
        if mask & (1 << 0): vram_tex += banks[0]
        elif mask & (1 << 1): vram_tex += banks[1]
        elif mask & (1 << 2): vram_tex += banks[2]
        elif mask & (1 << 3): vram_tex += banks[3]
        else: vram_tex += b"\0" * (128 << 10)

    for i in range(8):
        mask = rip.vram_map_texpal[i]
        if mask & (1 << 4): vram_pal += banks[4 + (i & 3)]
        elif mask & (1 << 5): vram_pal += banks[8]
        elif mask & (1 << 6): vram_pal += banks[9]
        else: vram_pal += b"\0" * (16 << 10)

    # Decode palette VRAM to u16s right away since its only read as u16s
    vram_pal = struct.unpack("<%dH" % (len(vram_pal) // 2), vram_pal)

    rip.vram_tex = vram_tex
    rip.vram_pal = vram_pal


def backwards_compat(rip):
    # Handle stuff missing from old .dump files
    if not hasattr(rip, 'disp_cnt'):
        rip.disp_cnt = 0
    if not hasattr(rip, 'toon_table'):
        rip.toon_table = [0xffff] * 32


# Precomputed table used for toon mode
# TOON_INDEX_TABLE[n]/255 is a color that will pick the nth texel
# when it's the texcoord to a 32x1 texture
TOON_INDEX_TABLE = [
    24,  60,  78,  93,  105, 115, 124, 132,
    140, 148, 155, 161, 167, 173, 179, 185,
    190, 195, 200, 205, 209, 214, 218, 222,
    226, 230, 234, 238, 242, 246, 249, 253,
]


def convert_vertex_colors(rip, colors):
    out = []
    is_highlight = ((rip.disp_cnt>>1) & 1) == 1

    for i in range(0, len(colors), 4):
        r = colors[i]
        g = colors[i+1]
        b = colors[i+2]
        is_toon_highlight = colors[i+3]

        if not is_toon_highlight:  # normal mode
            out += [r/31, g/31, b/31, 1.0]

        elif is_highlight:  # highlight mode
            out += [r/31, r/31, r/31, 1.0]

        else:  # toon mode
            c = TOON_INDEX_TABLE[r] / 255
            out += [c, c, c, 1.0]

    return out


# ---------
# Materials
# ---------

def create_material(rip, texparam, texpal, polygon_attr):
    # Basic NDS pixel pipeline as a Blender shader
    # Unimplemented: fog, toon, wireframe, cull frontfacing

    texformat = (texparam >> 26) & 7
    blendmode = (polygon_attr >> 4) & 0x3
    polyalpha = (polygon_attr >> 16) & 0x1F

    transparent = False  # on-off transparency
    translucent = False  # partial translucency
    texture_has_alpha = False
    if polyalpha < 31:
        translucent = True
    if texformat != 0 and blendmode in [0, 2]:
        if texformat in [1, 6]:  # translucent formats
            translucent = True
            texture_has_alpha = True
        if texformat in [2, 3, 4] and (texparam & (1<<29)):  # palettes with alpha0
            transparent = True
            texture_has_alpha = True
        if texformat == 5:  # compressed
            transparent = True
            texture_has_alpha = True

    mat = bpy.data.materials.new('NDS Material')

    if translucent:
        mat.blend_method = 'BLEND'
    elif transparent:
        mat.blend_method = 'CLIP'

    mat.use_backface_culling = bool((polygon_attr>>6)&1 == 0)

    mat.use_nodes = True
    while mat.node_tree.nodes:
        mat.node_tree.nodes.remove(mat.node_tree.nodes[0])
    output = mat.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
    output.location = 300, 300
    color_socket = output.inputs[0]

    tex_img = None

    x = 120

    alpha_socket = None
    if translucent or transparent:
        # Mix shader for alpha
        mix_trans = mat.node_tree.nodes.new(type='ShaderNodeMixShader')
        mix_trans.location = x, 230
        mat.node_tree.links.new(
            color_socket,
            mix_trans.outputs[0],
        )
        alpha_socket = mix_trans.inputs[0]
        color_socket = mix_trans.inputs[2]

        x -= 200

        trans_node = mat.node_tree.nodes.new(type='ShaderNodeBsdfTransparent')
        trans_node.location = x, -40
        mat.node_tree.links.new(
            mix_trans.inputs[1],
            trans_node.outputs[0],
        )

    if texformat != 0:
        # Mix the vertex color and texture together with blendmode
        mix = mat.node_tree.nodes.new(type='ShaderNodeMixRGB')
        mix.location = x, 350
        mat.node_tree.links.new(
            color_socket,
            mix.outputs[0],
        )
        color_socket = mix.inputs[1]

        if blendmode in [0, 2]:
            mix.label = 'Modulate'
            mix.blend_type = 'MULTIPLY'
            mix.inputs[0].default_value = 1
        else:
            mix.label = 'Decal'

        tex_img = texture_node(
            node_tree=mat.node_tree,
            image=get_texture(rip, texparam, texpal),
            repeat_s=bool( (texparam>>16) & 1 ),
            repeat_t=bool( (texparam>>17) & 1 ),
            flip_s=bool( (texparam>>18) & 1 ),
            flip_t=bool( (texparam>>19) & 1 ),
            location=(x - 70, 100),
        )
        mat.node_tree.links.new(
            mix.inputs[2],
            tex_img.outputs['Color'],
        )

        if blendmode in [1, 3]:  # Decal
            mat.node_tree.links.new(
                mix.inputs[0],
                tex_img.outputs['Alpha'],
            )

        if blendmode in [0,2] and texture_has_alpha:  # modulate + texture alpha
            socket = alpha_socket
            if polyalpha < 31:
                # Multiply poylalpha by texture alpha
                mul_alpha = mat.node_tree.nodes.new(type='ShaderNodeMath')
                mul_alpha.location = x, 150
                mul_alpha.operation = 'MULTIPLY'
                mat.node_tree.links.new(
                    socket,
                    mul_alpha.outputs[0],
                )
                mul_alpha.inputs[1].default_value = polyalpha / 31
                socket = mul_alpha.inputs[0]
            mat.node_tree.links.new(
                socket,
                tex_img.outputs['Alpha'],
            )
        elif alpha_socket:
            alpha_socket.default_value = polyalpha / 31

        x -= 120

    else:
        if alpha_socket:
            alpha_socket.default_value = polyalpha / 31

    loc = x - 100, 320
    if tex_img:
        loc = loc[0] - 40, loc[1] + 60
    vcolor_socket = vertex_color_node(
        rip=rip,
        node_tree=mat.node_tree,
        blendmode=blendmode,
        location=loc,
    )
    mat.node_tree.links.new(
        color_socket,
        vcolor_socket,
    )

    # Useful for debugging
    mat['nds:TexParam'] = str(texparam)
    mat['nds:TexPal'] = str(texpal)
    mat['nds:PolygonAttr'] = str(polygon_attr)
    mat['nds:Texture Format'] = str(texformat)
    mat['nds:Polygon Mode'] = str(blendmode)
    mat['nds:Polygon Alpha'] = str(polyalpha)
    mat['nds:Polygon Back Surface'] = str((polygon_attr>>6)&1)
    mat['nds:Polygon From Surface'] = str((polygon_attr>>7)&1)

    return mat


def texture_node(node_tree, image, repeat_s, repeat_t, flip_s, flip_t, location):
    x, y = location

    tex_img = node_tree.nodes.new('ShaderNodeTexImage')
    tex_img.location = x - 240, y
    tex_img.image = image
    tex_img.interpolation = 'Closest'
    uv_socket = tex_img.inputs['Vector']

    x -= 360

    # Wrapping
    if not repeat_s: flip_s = False
    if not repeat_t: flip_t = False
    if repeat_s == repeat_t and (not flip_s and not flip_t):
        tex_img.extension = 'REPEAT' if repeat_s else 'EXTEND'
    else:
        # Use math nodes to emulate other wrap modes
        # Based on the glTF importer

        tex_img.extension = 'EXTEND'

        frame = node_tree.nodes.new('NodeFrame')
        frame.label = 'Texcoord Wrapping'

        # Combine XYZ
        com_uv = node_tree.nodes.new('ShaderNodeCombineXYZ')
        com_uv.parent = frame
        com_uv.location = x - 80, y - 110
        node_tree.links.new(uv_socket, com_uv.outputs[0])
        u_socket = com_uv.inputs[0]
        v_socket = com_uv.inputs[1]
        x -= 120

        for i in [0, 1]:
            repeat = repeat_s if i == 0 else repeat_t
            flip = flip_s if i == 0 else flip_t
            socket = com_uv.inputs[i]
            if repeat and not flip:
                math = node_tree.nodes.new('ShaderNodeMath')
                math.parent = frame
                math.location = x - 140, y + 30 - i*200
                math.operation = 'WRAP'
                math.inputs[1].default_value = 0
                math.inputs[2].default_value = 1
                node_tree.links.new(socket, math.outputs[0])
                socket = math.inputs[0]
            elif repeat and flip:
                math = node_tree.nodes.new('ShaderNodeMath')
                math.parent = frame
                math.location = x - 140, y + 30 - i*200
                math.operation = 'PINGPONG'
                math.inputs[1].default_value = 1
                node_tree.links.new(socket, math.outputs[0])
                socket = math.inputs[0]
            else:
                # Clamp doesn't require a node since the default on the
                # Texture node is EXTEND.
                # Adjust node location for aesthetics though.
                if i == 0:
                    com_uv.location[1] += 90
            if i == 0:
                u_socket = socket
            else:
                v_socket = socket
        x -= 180

        # Separate XYZ
        sep_uv = node_tree.nodes.new('ShaderNodeSeparateXYZ')
        sep_uv.parent = frame
        sep_uv.location = x - 140, y - 100
        node_tree.links.new(u_socket, sep_uv.outputs[0])
        node_tree.links.new(v_socket, sep_uv.outputs[1])
        uv_socket = sep_uv.inputs[0]

        x -= 180

    if not tex_img.inputs['Vector'].is_linked:
        # UVs used automatically if Image Texture input unlinked
        pass
    else:
        uv_map = node_tree.nodes.new('ShaderNodeUVMap')
        uv_map.location = x - 160, y - 70
        uv_map.uv_map = 'UVMap'
        node_tree.links.new(uv_socket, uv_map.outputs[0])

    return tex_img


def vertex_color_node(rip, node_tree, blendmode, location):
    x, y = location
    shading = (rip.disp_cnt >> 1) & 1
    is_toon = blendmode == 2 and shading == 0

    if is_toon:
        toon_tex = node_tree.nodes.new('ShaderNodeTexImage')
        toon_tex.location = x - 50, y + 100
        toon_tex.image = get_toon_table_texture(rip)
        toon_tex.interpolation = 'Closest'
        toon_tex.extension = 'EXTEND'

        x -= 300

    vcolor = node_tree.nodes.new(type='ShaderNodeVertexColor')
    vcolor.location = x, y
    vcolor.layer_name = 'Col'

    if is_toon:
        node_tree.links.new(toon_tex.inputs[0], vcolor.outputs['Color'])
        return toon_tex.outputs['Color']
    else:
        return vcolor.outputs['Color']


def get_material(rip, texparam, texpal, polygon_attr):
    cache_key = (texparam, texpal, polygon_attr)
    mat = rip.material_cache.get(cache_key)
    if mat is None:
        mat = create_material(rip, texparam, texpal, polygon_attr)
        rip.material_cache[cache_key] = mat
    return mat


# --------
# Textures
# --------

def read_vram_texture_u8(rip, addr):
    return rip.vram_tex[addr & 0x7FFFF]


def read_vram_texture_u16(rip, addr):
    return (
        rip.vram_tex[addr & 0x7FFFF] |
        (rip.vram_tex[(addr+1) & 0x7FFFF] << 8)
    )


def read_vram_texpal_u16(rip, addr):
    return rip.vram_pal[(addr >> 1) & 0xFFFF]


def decode_texture(rip, texparam, texpal):
    # SLOW: texel fetching in Python is reallly slow (especially format 5)
    color = []
    alpha = []

    vramaddr = (texparam & 0xFFFF) << 3
    width = 8 << ((texparam >> 20) & 7)
    height = 8 << ((texparam >> 23) & 7)
    alpha0 = 0 if (texparam & (1<<29)) else 31
    texformat = (texparam >> 26) & 7

    if texformat == 1:  # A3I5
        texpal <<= 4
        for t in reversed(range(height)):  # reverse T direction so textures are right-side up
            for s in range(width):
                addr = vramaddr + (t*width)+s
                pixel = read_vram_texture_u8(rip, addr)
                color.append(read_vram_texpal_u16(rip, texpal + ((pixel&0x1F)<<1)))
                alpha.append( ((pixel>>3) & 0x1C) + (pixel>>6) )

    elif texformat == 2:  # 4-color
        texpal <<= 3
        for t in reversed(range(height)):
            for s in range(width):
                addr = vramaddr + (((t*width)+s)>>2)
                pixel = read_vram_texture_u8(rip, addr)
                pixel >>= (s & 3) << 1
                pixel &= 3

                color.append(read_vram_texpal_u16(rip, texpal + (pixel<<1)))
                alpha.append(alpha0 if pixel==0 else 31)

    elif texformat == 3:  # 16-color
        texpal <<= 4
        for t in reversed(range(height)):
            for s in range(width):
                addr = vramaddr + (((t*width)+s)>>1)
                pixel = read_vram_texture_u8(rip, addr)
                pixel = (pixel>>4) if (s&1) else (pixel&0xf)

                color.append(read_vram_texpal_u16(rip, texpal + (pixel<<1)))
                alpha.append(alpha0 if pixel==0 else 31)

    elif texformat == 4:  # 256-color
        texpal <<= 4
        for t in reversed(range(height)):
            for s in range(width):
                addr = vramaddr + ((t*width)+s)
                pixel = read_vram_texture_u8(rip, addr)

                color.append(read_vram_texpal_u16(rip, texpal + (pixel<<1)))
                alpha.append(alpha0 if pixel==0 else 31)

    elif texformat == 5:  # compressed
        texpal <<= 4
        for t in reversed(range(height)):
            for s in range(width):
                addr = vramaddr + ((t & 0x3FC) * (width>>2)) + (s & 0x3FC)
                addr += t & 3

                slot1addr = 0x20000 + ((addr & 0x1FFFC) >> 1)
                if addr >= 0x40000:
                    slot1addr += 0x10000

                val = read_vram_texture_u8(rip, addr)
                val >>= 2 * (s&3)

                palinfo = read_vram_texture_u16(rip, slot1addr)
                paloffset = (palinfo & 0x3FFF) << 2

                mode = val & 3
                if mode == 0:
                    color.append(read_vram_texpal_u16(rip, texpal + paloffset))
                    alpha.append(31)

                elif mode == 1:
                    color.append(read_vram_texpal_u16(rip, texpal + paloffset + 2))
                    alpha.append(31)

                elif mode == 2:
                    if (palinfo >> 14) == 1:
                        col0 = read_vram_texpal_u16(rip, texpal+paloffset)
                        col1 = read_vram_texpal_u16(rip, texpal+paloffset+2)

                        r0 = col0 & 0x001F
                        g0 = col0 & 0x03E0
                        b0 = col0 & 0x7C00
                        r1 = col1 & 0x001F
                        g1 = col1 & 0x03E0
                        b1 = col1 & 0x7C00

                        r = (r0 + r1) >> 1
                        g = ((g0 + g1) >> 1) & 0x03E0
                        b = ((b0 + b1) >> 1) & 0x7C00

                        color.append(r|g|b)
                    elif (palinfo >> 14) == 3:
                        col0 = read_vram_texpal_u16(rip, texpal+paloffset)
                        col1 = read_vram_texpal_u16(rip, texpal+paloffset+2)

                        r0 = col0 & 0x001F
                        g0 = col0 & 0x03E0
                        b0 = col0 & 0x7C00
                        r1 = col1 & 0x001F
                        g1 = col1 & 0x03E0
                        b1 = col1 & 0x7C00

                        r = (r0*5 + r1*3) >> 3
                        g = ((g0*5 + g1*3) >> 3) & 0x03E0
                        b = ((b0*5 + b1*3) >> 3) & 0x7C00

                        color.append(r|g|b)
                    else:
                        color.append(read_vram_texpal_u16(rip, texpal+paloffset+4))
                    alpha.append(31)

                else:
                    if (palinfo >> 14) == 2:
                        color.append(read_vram_texpal_u16(rip, texpal+paloffset+6))
                        alpha.append(31)
                    elif (palinfo >> 14) == 3:
                        col0 = read_vram_texpal_u16(rip, texpal+paloffset)
                        col1 = read_vram_texpal_u16(rip, texpal+paloffset+2)

                        r0 = col0 & 0x001F
                        g0 = col0 & 0x03E0
                        b0 = col0 & 0x7C00
                        r1 = col1 & 0x001F
                        g1 = col1 & 0x03E0
                        b1 = col1 & 0x7C00

                        r = (r0*3 + r1*5) >> 3
                        g = ((g0*3 + g1*5) >> 3) & 0x03E0
                        b = ((b0*3 + b1*5) >> 3) & 0x7C00

                        color.append(r|g|b)
                        alpha.append(31)
                    else:
                        color.append(0)
                        alpha.append(0)

    elif texformat == 6:  # A5I3
        texpal <<= 4
        for t in reversed(range(height)):
            for s in range(width):
                addr = vramaddr + (t*width)+s
                pixel = read_vram_texture_u8(rip, addr)
                color.append(read_vram_texpal_u16(rip, texpal + ((pixel&7)<<1)))
                alpha.append(pixel>>3)

    elif texformat == 7:  # direct color
        for t in reversed(range(height)):
            for s in range(width):
                addr = vramaddr + (((t*width)+s) << 1)
                pixel = read_vram_texture_u16(rip, addr)
                color.append(pixel)
                alpha.append(31 if (pixel & 0x8000) else 0)

    else:
        return None

    # Decode to floats
    pixels = []
    for i in range(len(color)):
        c, a = color[i], alpha[i]
        r = c & 0x1f
        g = (c >> 5) & 0x1f
        b = (c >> 10) & 0x1f
        pixels += [r/31, g/31, b/31, a/31]

    opaque = all(a == 31 for a in alpha)

    img = bpy.data.images.new('NDS Texture', width, height, alpha=not opaque)
    img.pixels[:] = pixels
    img.pack()

    return img


def get_texture(rip, texparam, texpal):
    # Cache on everything the texture depends on
    vramaddr = (texparam & 0xFFFF) << 3
    width = 8 << ((texparam >> 20) & 7)
    height = 8 << ((texparam >> 23) & 7)
    alpha0 = 0 if (texparam & (1<<29)) else 31
    texformat = (texparam >> 26) & 7
    # alpha0 only matters for paletted textures
    if texformat not in [2, 3, 4]: alpha0 = 0

    cache_key = (vramaddr, width, height, alpha0, texformat, texpal)

    img = rip.texture_cache.get(cache_key)
    if img is None:
        img = decode_texture(rip, texparam, texpal)
        rip.texture_cache[cache_key] = img
    return img


def get_toon_table_texture(rip):
    if rip.toon_table_texture is not None:
        return rip.toon_table_texture

    pixels = []
    for i in range(32):
        c = rip.toon_table[i]
        r = c & 0x1f
        g = (c >> 5) & 0x1f
        b = (c >> 10) & 0x1f
        pixels += [r/31, g/31, b/31, 1.0]

    img = bpy.data.images.new('NDS ToonTable', 32, 1, alpha=False)
    img.pixels[:] = pixels
    img.pack()

    rip.toon_table_texture = img
    return img


if __name__ == "__main__":
    register()
