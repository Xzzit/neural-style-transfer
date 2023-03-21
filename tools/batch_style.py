"""Neural style transfer (https://arxiv.org/abs/1508.06576) in PyTorch."""

import os
import io
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageCms
from tifffile import TIFF, TiffWriter
import torch
from tqdm import tqdm

from style_transfer import StyleTransfer

srgb_profile = (Path(__file__).resolve().parent / 'sRGB Profile.icc').read_bytes()


def prof_to_prof(image, src_prof, dst_prof, **kwargs):
    src_prof = io.BytesIO(src_prof)
    dst_prof = io.BytesIO(dst_prof)
    return ImageCms.profileToProfile(image, src_prof, dst_prof, **kwargs)


def load_image(path, proof_prof=None):
    src_prof = dst_prof = srgb_profile
    try:
        image = Image.open(path)
        if 'icc_profile' in image.info:
            src_prof = image.info['icc_profile']
        else:
            image = image.convert('RGB')
        if proof_prof is None:
            if src_prof == dst_prof:
                return image.convert('RGB')
            return prof_to_prof(image, src_prof, dst_prof, outputMode='RGB')
        proof_prof = Path(proof_prof).read_bytes()
        cmyk = prof_to_prof(image, src_prof, proof_prof, outputMode='CMYK')
        return prof_to_prof(cmyk, proof_prof, dst_prof, outputMode='RGB')
    except OSError as err:
        print_error(err)
        sys.exit(1)


def save_pil(path, image):
    try:
        kwargs = {'icc_profile': srgb_profile}
        if path.suffix.lower() in {'.jpg', '.jpeg'}:
            kwargs['quality'] = 95
            kwargs['subsampling'] = 0
        elif path.suffix.lower() == '.webp':
            kwargs['quality'] = 95
        image.save(path, **kwargs)
    except (OSError, ValueError) as err:
        print_error(err)
        sys.exit(1)


def save_tiff(path, image):
    tag = ('InterColorProfile', TIFF.DATATYPES.BYTE, len(srgb_profile), srgb_profile, False)
    try:
        with TiffWriter(path) as writer:
            writer.save(image, photometric='rgb', resolution=(72, 72), extratags=[tag])
    except OSError as err:
        print_error(err)
        sys.exit(1)


def save_image(path, image):
    path = Path(path)
    tqdm.write(f'Writing image to {path}.')
    if isinstance(image, Image.Image):
        save_pil(path, image)
    elif isinstance(image, np.ndarray) and path.suffix.lower() in {'.tif', '.tiff'}:
        save_tiff(path, image)
    else:
        raise ValueError('Unsupported combination of image type and extension')


def get_safe_scale(w, h, dim):
    """Given a w x h content image and that a dim x dim square does not
    exceed GPU memory, compute a safe end_scale for that content image."""
    return int(pow(w / h if w > h else h / w, 1/2) * dim)


def print_error(err):
    print('\033[31m{}:\033[0m {}'.format(type(err).__name__, err), file=sys.stderr)


def stylize(content_path, styles_path, save_dir):

    content_img = load_image(content_path)
    style_imgs = [load_image(styles_path)]

    image_type = 'pil'

    devices = [torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')]
    if len(set(device.type for device in devices)) != 1:
        print('Devices must all be the same type.')
        sys.exit(1)
    if not 1 <= len(devices) <= 2:
        print('Only 1 or 2 devices are supported.')
        sys.exit(1)
    print('Using devices:', ' '.join(str(device) for device in devices))

    if devices[0].type == 'cpu':
        print('CPU threads:', torch.get_num_threads())
    if devices[0].type == 'cuda':
        for i, device in enumerate(devices):
            props = torch.cuda.get_device_properties(device)
            print(f'GPU {i} type: {props.name} (compute {props.major}.{props.minor})')
            print(f'GPU {i} RAM:', round(props.total_memory / 1024**3), 'GB')

    end_scale = int(max(content_img.size[0], content_img.size[1]))

    for device in devices:
        torch.tensor(0).to(device)
    torch.manual_seed(0)

    print('Loading model...')
    st = StyleTransfer(devices=devices, pooling='max')

    try:
        st.stylize(content_img, style_imgs, end_scale=end_scale)
    except KeyboardInterrupt:
        pass

    output_image = st.get_image(image_type)
    if output_image is not None:
        save_image(save_dir, output_image)


if __name__ == '__main__':

    content_path = '/home/zjlab/xzz/datasets/Camera1'
    style_path = '/home/zjlab/xzz/datasets/style/vangoh.jpeg'
    save_dir = '/home/zjlab/xzz/datasets/Camera1_style'

    for i in os.listdir(content_path):
        content_img = os.path.join(content_path, i)
        stylize(content_img, style_path, os.path.join(save_dir, i))
