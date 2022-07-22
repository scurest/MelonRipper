
# ███╗   ███╗███████╗██╗      ██████╗ ███╗   ██╗██████╗ ██╗██████╗ ██████╗ ███████╗██████╗
# ████╗ ████║██╔════╝██║     ██╔═══██╗████╗  ██║██╔══██╗██║██╔══██╗██╔══██╗██╔════╝██╔══██╗
# ██╔████╔██║█████╗  ██║     ██║   ██║██╔██╗ ██║██████╔╝██║██████╔╝██████╔╝█████╗  ██████╔╝
# ██║╚██╔╝██║██╔══╝  ██║     ██║   ██║██║╚██╗██║██╔══██╗██║██╔═══╝ ██╔═══╝ ██╔══╝  ██╔══██╗
# ██║ ╚═╝ ██║███████╗███████╗╚██████╔╝██║ ╚████║██║  ██║██║██║     ██║     ███████╗██║  ██║
# ╚═╝     ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝╚═╝     ╚═╝     ╚══════╝╚═╝  ╚═╝

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
import os
import struct
import time

from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper


class ShowErrorMsg(RuntimeError):
    # Raise to show an error message
    pass


class ImportMelonRipOp(bpy.types.Operator, ImportHelper):
    """Load a MelonRipper DS .dump file"""
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

        try:
            import_rip(self.filepath)

        except ShowErrorMsg as e:
            self.report({'ERROR'}, e.args[0])
            return {'CANCELLED'}

        end_t = time.time()
        elapsed = end_t - start_t

        print(f"Imported '{self.filepath}' in {elapsed:.1f} s")

        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator(ImportMelonRipOp.bl_idname, text="MelonRipper NDS Dump")


def register():
    bpy.utils.register_class(ImportMelonRipOp)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ImportMelonRipOp)


if __name__ == "__main__":
    register()


#  # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#  # # # # # # # # # # # # # # # # # # # # # # # # # # #


# Precomputed table used for toon mode.
# TOON_INDEX_TABLE[n]/255 is a color that will pick the nth texel
# when used as the UV for a 32x1 texture.
TOON_INDEX_TABLE = [
    24,  60,  78,  93,  105, 115, 124, 132,
    140, 148, 155, 161, 167, 173, 179, 185,
    190, 195, 200, 205, 209, 214, 218, 222,
    226, 230, 234, 238, 242, 246, 249, 253,
]


def import_rip(filepath):
    name = os.path.basename(filepath)
    if name.endswith('.dump'):
        name = name[:-len('.dump')]  # remove suffix

    with open(filepath, 'rb') as f:
        dump = f.read()

    rip = Rip(dump)
    rip.parse()

    importer = Importer(name, rip)
    importer.create_blender_objects()


class Rip:
    """Handles parsing .dump file."""

    def __init__(self, dump):
        self.dump = dump

        # Default value for stuff missing from older versions of .dump
        # files; initialize for backwards compatiblity.
        self.disp_cnt = 0
        self.toon_table = [0xFFFF] * 32

    def check_magic(self):
        magic = self.dump[:24]
        magic = magic.rstrip(b'\0')
        prefix = b'melon ripper v'
        if not magic.startswith(prefix):
            raise ShowErrorMsg('Not a MelonRipper file')

        version = magic[len(prefix):]  # remove prefix
        try:
            version = int(str(version, encoding='ascii'))
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
                'MelonRipper file too new, update this addon! '
                'Version is %d; I only support %d' % (version, max_version)
            )

    def parse(self):
        self.check_magic()

        pos = 24  # end of magic

        verts = []
        colors = []
        uvs = []
        faces = []
        face_materials = []
        materials = {}

        texparam = 0
        texpal = 0
        polygon_attr = 0
        blend_mode = 0
        texture_width = 8
        texture_height = 8

        dump = self.dump
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
                    verts.append((x, -z, y))  # switch Yup2Zup

                    r, g, b = struct.unpack_from('<3i', dump, offset=pos)
                    pos += 4*3
                    # Get back to 0-31 range (undo melonDS transform)
                    r = (r - 0xFFF) >> 12
                    g = (g - 0xFFF) >> 12
                    b = (b - 0xFFF) >> 12
                    colors += [r, g, b]
                    # The final vertex color is affected by whether
                    # toon/highlight mode is enabled in disp_cnt, but
                    # that doesn't come until the end of the file. So
                    # for now just remember this so we can compute the
                    # final color at the end.
                    use_toon_highlight = (blend_mode == 2)
                    colors.append(use_toon_highlight)

                    s, t = struct.unpack_from('<2h', dump, offset=pos)
                    pos += 2*2
                    # Textures are upside down in Blender, so we flip them,
                    # but that means we need to flip the T coord too.
                    uvs += [s/16/texture_width, 1 - t/16/texture_height]

                material_args = (texparam, texpal, polygon_attr)
                if material_args not in materials:
                    materials[material_args] = len(materials)
                material_index = materials[material_args]

                faces.append(tuple(range(vert_index, vert_index + nverts)))
                face_materials.append(material_index)

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
                blend_mode = (polygon_attr >> 4) & 3
                pos += 4

            elif op == b"VRAM":
                self.vram_map_texture = struct.unpack_from('<4I', dump, offset=pos)
                pos += 4*4

                self.vram_map_texpal = struct.unpack_from('<8I', dump, offset=pos)
                pos += 4*8

                banks = []

                # Banks A-D, 128K each
                for _ in range(4):
                    banks.append(dump[pos : pos + (128 << 10)])
                    pos += 128 << 10

                # Banks E-G, E is 64K, F-G are 16K
                for _ in range(6):
                    banks.append(dump[pos : pos + (16 << 10)])
                    pos += 16 << 10

                self.load_vram(banks)

            elif op == b"DISP":
                self.disp_cnt, = struct.unpack_from('<I', dump, offset=pos)
                pos += 4

            elif op == b"TOON":
                self.toon_table = struct.unpack_from('<32H', dump, offset=pos)
                pos += 2*32

            else:
                raise RuntimeError('unknown opcode in MelonRipper file')

        self.verts = verts
        self.colors = self.finalize_colors(colors)
        self.uvs = uvs
        self.faces = faces
        self.face_materials = face_materials
        self.materials = materials

    def finalize_colors(self, tmp):
        colors = []
        is_highlight = ((self.disp_cnt>>1) & 1) == 1

        for i in range(0, len(tmp), 4):
            r, g, b, is_toon_highlight = tmp[i:i+4]

            if not is_toon_highlight:
                # Normal color
                colors += [r/31, g/31, b/31, 1.0]

            elif is_highlight:
                # Highlight mode
                colors += [r/31, r/31, r/31, 1.0]

            else:
                # Toon mode
                c = TOON_INDEX_TABLE[r] / 255
                colors += [c, c, c, 1.0]

        return colors

    def load_vram(self, banks):
        # Use the memory map to compute how banks are laid out in VRAM.
        vram_tex = bytearray()
        vram_pal = bytearray()

        for i in range(4):
            mask = self.vram_map_texture[i]
            if mask & (1 << 0): vram_tex += banks[0]
            elif mask & (1 << 1): vram_tex += banks[1]
            elif mask & (1 << 2): vram_tex += banks[2]
            elif mask & (1 << 3): vram_tex += banks[3]
            else: vram_tex += b"\0" * (128 << 10)

        for i in range(8):
            mask = self.vram_map_texpal[i]
            if mask & (1 << 4): vram_pal += banks[4 + (i & 3)]
            elif mask & (1 << 5): vram_pal += banks[8]
            elif mask & (1 << 6): vram_pal += banks[9]
            else: vram_pal += b"\0" * (16 << 10)

        # Palette memory always read as u16s, decode it now.
        vram_pal = struct.unpack("<%dH" % (len(vram_pal) // 2), vram_pal)

        self.vram_tex = vram_tex
        self.vram_pal = vram_pal


class Importer:
    """Handles creating Blender objects."""

    def __init__(self, name, rip):
        self.name = name
        self.rip = rip

        # Initialize caches
        self.texture_cache = {}
        self.toon_table = None

    def create_blender_objects(self):
        rip = self.rip

        mesh = bpy.data.meshes.new(self.name)
        mesh.from_pydata(rip.verts, [], rip.faces)

        vertex_colors = mesh.vertex_colors.new()
        vertex_colors.data.foreach_set('color', rip.colors)

        uvs = mesh.uv_layers.new()
        uvs.data.foreach_set('uv', rip.uvs)

        mesh.polygons.foreach_set('material_index', rip.face_materials)

        mesh.validate()

        for material_args in rip.materials:
            mesh.materials.append(self.create_material(*material_args))

        ob = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.scene.collection.objects.link(ob)

        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob

    def get_texture(self, texparam, texpal):
        vramaddr = (texparam & 0xFFFF) << 3
        width = 8 << ((texparam >> 20) & 7)
        height = 8 << ((texparam >> 23) & 7)
        alpha0 = 0 if (texparam & (1<<29)) else 31
        texformat = (texparam >> 26) & 7
        # alpha0 only matters for paletted textures
        if texformat not in [2, 3, 4]:
            alpha0 = 0

        # Cache on everything the texture depends on
        cache_key = (vramaddr, width, height, alpha0, texformat, texpal)

        if cache_key not in self.texture_cache:
            self.texture_cache[cache_key] = self.create_texture(texparam, texpal)

        return self.texture_cache[cache_key]

    def create_texture(self, texparam, texpal):
        width = 8 << ((texparam >> 20) & 7)
        height = 8 << ((texparam >> 23) & 7)

        pixels, is_opaque = decode_texture(self.rip, texparam, texpal)

        img = bpy.data.images.new('NDS Texture', width, height, alpha=not is_opaque)
        img.pixels[:] = pixels
        img.pack()

        return img

    def get_toon_table(self):
        if self.toon_table is None:
            self.toon_table = self.create_toon_table()
        return self.toon_table

    def create_toon_table(self):
        pixels = []
        for i in range(32):
            c = self.rip.toon_table[i]
            r = c & 0x1f
            g = (c >> 5) & 0x1f
            b = (c >> 10) & 0x1f
            pixels += [r/31, g/31, b/31, 1.0]

        img = bpy.data.images.new('NDS ToonTable', 32, 1, alpha=False)
        img.pixels[:] = pixels
        img.pack()

        return img

    def create_material(self, texparam, texpal, polygon_attr):
        mat = bpy.data.materials.new('NDS Material')

        texformat = (texparam >> 26) & 7
        blend_mode = (polygon_attr >> 4) & 0x3
        poly_alpha = (polygon_attr >> 16) & 0x1F
        shading = (self.rip.disp_cnt >> 1) & 1

        texture = self.get_texture(texparam, texpal) if texformat != 0 else None

        is_toon = blend_mode == 2 and shading == 0
        toon_table = self.get_toon_table() if is_toon else None

        if poly_alpha < 31:
            mat.blend_method = 'BLEND'
        elif texture and blend_mode in [0, 2]:
            if texformat in [1, 6]:
                # Translucent texture
                mat.blend_method = 'BLEND'
            elif texformat in [2, 3, 4] and (texparam & (1<<29)):
                # Palette texture with transparent alpha0
                mat.blend_method = 'CLIP'
            elif texformat == 5:
                # Compressed texture
                mat.blend_method = 'CLIP'

        mat.use_backface_culling = (polygon_attr>>6) & 1 == 0

        mat.use_nodes = True
        setup_nodetree(
            node_tree=mat.node_tree,
            poly_alpha=poly_alpha,
            texture=texture,
            repeat_s=bool( (texparam>>16) & 1 ),
            repeat_t=bool( (texparam>>17) & 1 ),
            flip_s=bool( (texparam>>18) & 1 ),
            flip_t=bool( (texparam>>19) & 1 ),
            blend_mode=blend_mode,
            toon_table=toon_table
        )

        # Useful for debugging.
        mat['nds:TexParam'] = str(texparam)
        mat['nds:TexPal'] = str(texpal)
        mat['nds:PolygonAttr'] = str(polygon_attr)
        mat['nds:Texture Format'] = str(texformat)
        mat['nds:Polygon Mode'] = str(blend_mode)
        mat['nds:Polygon Alpha'] = str(poly_alpha)
        mat['nds:Polygon Back Surface'] = str((polygon_attr>>6)&1)
        mat['nds:Polygon From Surface'] = str((polygon_attr>>7)&1)

        return mat


def setup_nodetree(
    node_tree,
    poly_alpha,
    texture,
    repeat_s, repeat_t,
    flip_s, flip_t,
    blend_mode,
    toon_table,
):
    # Will look like
    #
    #  [ Vertex Color ] - [Combine] - [Transparency] - [Output]
    #                   /
    #          [Texture]
    #
    texture_has_alpha = texture and texture.depth == 32
    needs_alpha = poly_alpha < 31 or (texture_has_alpha and blend_mode in [0, 2])
    x = 120

    # Clear existing nodes
    while node_tree.nodes:
        node_tree.nodes.remove(node_tree.nodes[0])

    # Output node
    output = node_tree.nodes.new(type='ShaderNodeOutputMaterial')
    output.location = 300, 300
    socket = output.inputs[0]

    # Tranparency
    if needs_alpha:
        mix_transp = node_tree.nodes.new(type='ShaderNodeMixShader')
        mix_transp.location = x, 230
        mix_transp.inputs[0].default_value = poly_alpha / 31
        node_tree.links.new(socket, mix_transp.outputs[0])

        transp = node_tree.nodes.new(type='ShaderNodeBsdfTransparent')
        transp.location = x - 200, -30
        node_tree.links.new(mix_transp.inputs[1], transp.outputs[0])

        socket = mix_transp.inputs[2]
        x -= 200

    if texture:
        # Mix node to combine vertex color and texture with the blend mode
        mix = node_tree.nodes.new(type='ShaderNodeMixRGB')
        mix.location = x, 350
        node_tree.links.new(socket, mix.outputs[0])

        # Texture
        tex_img = texture_node(
            node_tree=node_tree,
            image=texture,
            repeat_s=repeat_s,
            repeat_t=repeat_t,
            flip_s=flip_s,
            flip_t=flip_t,
            location=(x - 70, 100),
        )

        if blend_mode in [0, 2]:
            # Modulate mode: vertex_color * texture_color
            mix.label = 'Modulate'
            mix.blend_type = 'MULTIPLY'
            mix.inputs[0].default_value = 1
            node_tree.links.new(mix.inputs[2], tex_img.outputs['Color'])

            # Connect texture alpha to transparency
            if texture_has_alpha:
                if poly_alpha == 31:
                    node_tree.links.new(mix_transp.inputs[0], tex_img.outputs['Alpha'])
                else:
                    # Multiply poly_alpha and texture_alpha
                    mul_alpha = node_tree.nodes.new(type='ShaderNodeMath')
                    mul_alpha.location = x, 150
                    mul_alpha.operation = 'MULTIPLY'
                    mul_alpha.inputs[1].default_value = poly_alpha / 31
                    node_tree.links.new(mix_transp.inputs[0], mul_alpha.outputs[0])
                    node_tree.links.new(mul_alpha.inputs[0], tex_img.outputs['Alpha'])

        else:
            # Decal mode; texture alpha is the mix factor
            mix.label = 'Decal'
            mix.blend_type = 'MIX'
            node_tree.links.new(mix.inputs[0], tex_img.outputs['Alpha'])
            node_tree.links.new(mix.inputs[2], tex_img.outputs['Color'])

        socket = mix.inputs[1]
        x -= 120

    x, y = x - 100, 320
    if texture:
        x, y = x - 40, y + 60

    # Toon table
    if toon_table:
        toon_tex = node_tree.nodes.new('ShaderNodeTexImage')
        toon_tex.location = x - 50, y + 100
        toon_tex.image = toon_table
        toon_tex.interpolation = 'Closest'
        toon_tex.extension = 'EXTEND'
        node_tree.links.new(socket, toon_tex.outputs['Color'])

        socket = toon_tex.inputs[0]
        x -= 300

    # Vertex color
    vcolor = node_tree.nodes.new(type='ShaderNodeVertexColor')
    vcolor.location = x, y
    vcolor.layer_name = 'Col'
    node_tree.links.new(socket, vcolor.outputs['Color'])


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
    if repeat_s == repeat_t and not flip_s and not flip_t:
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

        # UVMap node
        uv_map = node_tree.nodes.new('ShaderNodeUVMap')
        uv_map.location = x - 160, y - 70
        uv_map.uv_map = 'UVMap'
        node_tree.links.new(uv_socket, uv_map.outputs[0])

    return tex_img


def decode_texture(rip, texparam, texpal):
    color = []
    alpha = []

    vramaddr = (texparam & 0xFFFF) << 3
    width = 8 << ((texparam >> 20) & 7)
    height = 8 << ((texparam >> 23) & 7)
    alpha0 = 0 if (texparam & (1<<29)) else 31
    texformat = (texparam >> 26) & 7

    vram_tex = rip.vram_tex
    vram_pal = rip.vram_pal

    if texformat == 1:  # A3I5
        texpal <<= 3
        for addr in range(vramaddr, vramaddr + width*height):
            pixel = vram_tex[addr & 0x7FFFF]
            color.append(vram_pal[( texpal + (pixel&0x1F) ) & 0xFFFF])
            alpha.append( ((pixel>>3) & 0x1C) + (pixel>>6) )

    elif texformat == 6:  # A5I3
        texpal <<= 3
        for addr in range(vramaddr, vramaddr + width*height):
            pixel = vram_tex[addr & 0x7FFFF]
            color.append(vram_pal[( texpal + (pixel&0x7) ) & 0xFFFF])
            alpha.append(pixel>>3)

    elif texformat == 2:  # 4-color
        texpal <<= 2
        for addr in range(vramaddr, vramaddr + width*height//4):
            pixelx4 = vram_tex[addr & 0x7FFFF]
            p0 = pixelx4 & 0x3
            p1 = (pixelx4 >> 2) & 0x3
            p2 = (pixelx4 >> 4) & 0x3
            p3 = pixelx4 >> 6

            color.append(vram_pal[( texpal + p0 ) & 0xFFFF])
            color.append(vram_pal[( texpal + p1 ) & 0xFFFF])
            color.append(vram_pal[( texpal + p2 ) & 0xFFFF])
            color.append(vram_pal[( texpal + p3 ) & 0xFFFF])

            alpha.append(alpha0 if p0==0 else 31)
            alpha.append(alpha0 if p1==0 else 31)
            alpha.append(alpha0 if p2==0 else 31)
            alpha.append(alpha0 if p3==0 else 31)

    elif texformat == 3:  # 16-color
        texpal <<= 3
        for addr in range(vramaddr, vramaddr + width*height//2):
            pixelx2 = vram_tex[addr & 0x7FFFF]
            p0 = pixelx2 & 0xF
            p1 = pixelx2 >> 4

            color.append(vram_pal[( texpal + p0 ) & 0xFFFF])
            color.append(vram_pal[( texpal + p1 ) & 0xFFFF])

            alpha.append(alpha0 if p0==0 else 31)
            alpha.append(alpha0 if p1==0 else 31)

    elif texformat == 4:  # 256-color
        texpal <<= 3
        for addr in range(vramaddr, vramaddr + width*height):
            pixel = vram_tex[addr & 0x7FFFF]
            color.append(vram_pal[( texpal + pixel ) & 0xFFFF])
            alpha.append(alpha0 if pixel==0 else 31)

    elif texformat == 7:  # direct color
        for addr in range(vramaddr, vramaddr + width*height*2, 2):
            pixel = rip.vram_tex[addr & 0x7FFFF]
            pixel |= rip.vram_tex[(addr+1) & 0x7FFFF] << 8
            color.append(pixel)
            alpha.append(31 if (pixel & 0x8000) else 0)

    elif texformat == 5:  # compressed
        color = [0] * (width * height)
        alpha = [0] * (width * height)
        block_color = [0, 0, 0, 0]
        block_alpha = [31, 31, 31, 31]
        x_ofs = 0
        y_ofs = 0

        texpal <<= 3

        for addr in range(vramaddr, vramaddr + width*height//4, 4):

            # Read slot1 data for this block

            slot1addr = 0x20000 + ((addr & 0x1FFFC) >> 1)
            if addr >= 0x40000:
                slot1addr += 0x10000

            palinfo = vram_tex[slot1addr & 0x7FFFF]
            palinfo |= vram_tex[(slot1addr + 1) & 0x7FFFF] << 8
            paloffset = texpal + ((palinfo & 0x3FFF) << 1)
            palmode = palinfo >> 14

            # Calculate block CLUT

            col0 = vram_pal[( paloffset ) & 0xFFFF]
            col1 = vram_pal[( paloffset + 1 ) & 0xFFFF]
            block_color[0] = col0
            block_color[1] = col1
            block_alpha[3] = 31 if palmode >= 2 else 0

            if palmode == 0:
                block_color[2] = vram_pal[( paloffset + 2 ) & 0xFFFF]
                block_color[3] = 0

            elif palmode == 2:
                block_color[2] = vram_pal[( paloffset + 2 ) & 0xFFFF]
                block_color[3] = vram_pal[( paloffset + 3 ) & 0xFFFF]

            elif palmode == 1:
                r0 = col0 & 0x001F
                g0 = col0 & 0x03E0
                b0 = col0 & 0x7C00
                r1 = col1 & 0x001F
                g1 = col1 & 0x03E0
                b1 = col1 & 0x7C00

                r2 = (r0 + r1) >> 1
                g2 = ((g0 + g1) >> 1) & 0x03E0
                b2 = ((b0 + b1) >> 1) & 0x7C00

                block_color[2] = r2 | g2 | b2
                block_color[3] = 0

            else:
                r0 = col0 & 0x001F
                g0 = col0 & 0x03E0
                b0 = col0 & 0x7C00
                r1 = col1 & 0x001F
                g1 = col1 & 0x03E0
                b1 = col1 & 0x7C00

                r2 = (r0*5 + r1*3) >> 3
                g2 = ((g0*5 + g1*3) >> 3) & 0x03E0
                b2 = ((b0*5 + b1*3) >> 3) & 0x7C00

                r3 = (r0*3 + r1*5) >> 3
                g3 = ((g0*3 + g1*5) >> 3) & 0x03E0
                b3 = ((b0*3 + b1*5) >> 3) & 0x7C00

                block_color[2] = r2 | g2 | b2
                block_color[3] = r3 | g3 | b3

            # Read block of 4x4 pixels at addr
            # 2bpp indices into the block CLUT

            for y in range(4):
                ofs = y_ofs + y*width + x_ofs

                pixelx4 = vram_tex[(addr + y) & 0x7FFFF]

                p0 = pixelx4 & 0x3
                p1 = (pixelx4 >> 2) & 0x3
                p2 = (pixelx4 >> 4) & 0x3
                p3 = pixelx4 >> 6

                color[ofs] = block_color[p0]
                color[ofs+1] = block_color[p1]
                color[ofs+2] = block_color[p2]
                color[ofs+3] = block_color[p3]

                alpha[ofs] = block_alpha[p0]
                alpha[ofs+1] = block_alpha[p1]
                alpha[ofs+2] = block_alpha[p2]
                alpha[ofs+3] = block_alpha[p3]

            # Advance to next block position

            x_ofs += 4
            if x_ofs == width:
                x_ofs = 0
                y_ofs += 4*width

    # Decode to floats
    # Also reverse the rows so the image is right-side-up
    pixels = []
    for t in reversed(range(height)):
        for i in range(t*width, (t+1)*width):
            c, a = color[i], alpha[i]
            r = c & 0x1f
            g = (c >> 5) & 0x1f
            b = (c >> 10) & 0x1f
            pixels += [r/31, g/31, b/31, a/31]

    is_opaque = all(a == 31 for a in alpha)

    return pixels, is_opaque
