import cog
import tempfile
from pathlib import Path
import argparse
import shutil
import os
import cv2
import glob
import torch
from collections import OrderedDict
import numpy as np
from main_test_SwinIR import define_model, setup, get_image_pair


class Predictor(cog.Predictor):
    def setup(self):
        model_dir =  f"{os.path.dirname(__file__)}\model_zoo"

        self.model_zoo = {
            'real_sr': {
                4: os.path.join(model_dir, '003_realSR_BSRGAN_DFO_s64w8_SwinIR-M_x4_GAN.pth')
            },
            'gray_dn': {
                15: os.path.join(model_dir, '004_grayDN_DFWB_s128w8_SwinIR-M_noise15.pth'),
                25: os.path.join(model_dir, '004_grayDN_DFWB_s128w8_SwinIR-M_noise25.pth'),
                50: os.path.join(model_dir, '004_grayDN_DFWB_s128w8_SwinIR-M_noise50.pth')
            },
            'color_dn': {
                15: os.path.join(model_dir, '005_colorDN_DFWB_s128w8_SwinIR-M_noise15.pth'),
                25: os.path.join(model_dir, '005_colorDN_DFWB_s128w8_SwinIR-M_noise25.pth'),
                50: os.path.join(model_dir, '005_colorDN_DFWB_s128w8_SwinIR-M_noise50.pth')
            },
            'jpeg_car': {
                10: os.path.join(model_dir, '006_CAR_DFWB_s126w7_SwinIR-M_jpeg10.pth'),
                20: os.path.join(model_dir, '006_CAR_DFWB_s126w7_SwinIR-M_jpeg20.pth'),
                30: os.path.join(model_dir, '006_CAR_DFWB_s126w7_SwinIR-M_jpeg30.pth'),
                40: os.path.join(model_dir, '006_CAR_DFWB_s126w7_SwinIR-M_jpeg40.pth')
            }
        }

        parser = argparse.ArgumentParser()
        parser.add_argument('--task', type=str, default='real_sr', help='classical_sr, lightweight_sr, real_sr, '
                                                                        'gray_dn, color_dn, jpeg_car')
        parser.add_argument('--scale', type=int, default=4, help='scale factor: 1, 2, 3, 4, 8')  # 1 for dn and jpeg car
        parser.add_argument('--noise', type=int, default=15, help='noise level: 15, 25, 50')
        parser.add_argument('--jpeg', type=int, default=40, help='scale factor: 10, 20, 30, 40')
        parser.add_argument('--training_patch_size', type=int, default=128, help='patch size used in training SwinIR. '
                                                                                 'Just used to differentiate two different settings in Table 2 of the paper. '
                                                                                 'Images are NOT tested patch by patch.')
        parser.add_argument('--large_model', action='store_true',
                            help='use large model, only provided for real image sr')
        parser.add_argument('--model_path', type=str,
                            default=self.model_zoo['real_sr'][4])
        parser.add_argument('--folder_lq', type=str, default=None, help='input low-quality test image folder')
        parser.add_argument('--folder_gt', type=str, default=None, help='input ground-truth test image folder')

        self.args = parser.parse_args('')

        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        self.tasks = {
            'Real-World Image Super-Resolution': 'real_sr',
            'Grayscale Image Denoising': 'gray_dn',
            'Color Image Denoising': 'color_dn',
            'JPEG Compression Artifact Reduction': 'jpeg_car'
        }

    @cog.input("image", type=Path, help="input image")
    @cog.input("task_type", type=str, default='Real-World Image Super-Resolution',
               options=['Real-World Image Super-Resolution', 'Grayscale Image Denoising', 'Color Image Denoising',
                        'JPEG Compression Artifact Reduction'],
               help="image restoration task type")
    @cog.input("noise", type=int, default=15, options=[15, 25, 50],
               help='noise level, activated for Grayscale Image Denoising and Color Image Denoising. '
                    'Leave it as default or arbitrary if other tasks are selected')
    @cog.input("jpeg", type=int, default=40, options=[10, 20, 30, 40],
               help='scale factor, activated for JPEG Compression Artifact Reduction. '
                    'Leave it as default or arbitrary if other tasks are selected')

    def predict(self, image, task_type='Real-World Image Super-Resolution', jpeg=40, noise=15,out_path=None):

        self.args.task = self.tasks[task_type]
        self.args.noise = noise
        self.args.jpeg = jpeg

        # 设置模型路径
        if self.args.task == 'real_sr':
            self.args.scale = 4
            self.args.model_path = self.model_zoo[self.args.task][4]
        elif self.args.task in ['gray_dn', 'color_dn']:
            self.args.model_path = self.model_zoo[self.args.task][noise]
        else:
            self.args.model_path = self.model_zoo[self.args.task][jpeg]

        input_dir = 'input_cog_temp'
        try:
            # 设置输入备份文件夹
            os.makedirs(input_dir, exist_ok=True)
            input_path = os.path.join(input_dir, os.path.basename(image))
            shutil.copy(str(image), input_path)
            if self.args.task == 'real_sr':
                #将图片备份到低分辨率文件夹作为预测对象
                self.args.folder_lq = input_dir
            else:
                self.args.folder_gt = input_dir
            #加载模型
            model = define_model(self.args)
            model.eval()
            model = model.to(self.device)

            #设置文件夹和路径
            folder, save_dir, border, window_size = setup(self.args)
            os.makedirs(save_dir, exist_ok=True)
            test_results = OrderedDict()
            test_results['psnr'] = []
            test_results['ssim'] = []
            test_results['psnr_y'] = []
            test_results['ssim_y'] = []
            test_results['psnr_b'] = []
            # psnr, ssim, psnr_y, ssim_y, psnr_b = 0, 0, 0, 0, 0
            #设置输出目录
            if out_path is None:
                out_path = Path(image).parent / "out.png"

            for idx, path in enumerate(sorted(glob.glob(os.path.join(folder, '*')))):
                # 阅读图片
                imgname, img_lq, img_gt = get_image_pair(self.args, path)  # image to HWC-BGR, float32
                img_lq = np.transpose(img_lq if img_lq.shape[2] == 1 else img_lq[:, :, [2, 1, 0]],
                                      (2, 0, 1))  # HCW-BGR to CHW-RGB
                img_lq = torch.from_numpy(img_lq).float().unsqueeze(0).to(self.device)  # CHW-RGB to NCHW-RGB

                # 推理
                with torch.no_grad():
                    # 键盘输入图像为window_size的倍数
                    _, _, h_old, w_old = img_lq.size()
                    h_pad = (h_old // window_size + 1) * window_size - h_old
                    w_pad = (w_old // window_size + 1) * window_size - w_old
                    img_lq = torch.cat([img_lq, torch.flip(img_lq, [2])], 2)[:, :, :h_old + h_pad, :]
                    img_lq = torch.cat([img_lq, torch.flip(img_lq, [3])], 3)[:, :, :, :w_old + w_pad]
                    output = model(img_lq)
                    output = output[..., :h_old * self.args.scale, :w_old * self.args.scale]

                # 保存图片
                output = output.data.squeeze().float().cpu().clamp_(0, 1).numpy()
                if output.ndim == 3:
                    output = np.transpose(output[[2, 1, 0], :, :], (1, 2, 0))  # CHW-RGB to HCW-BGR
                output = (output * 255.0).round().astype(np.uint8)  # float32 to uint8
                cv2.imwrite(str(out_path), output)
        finally:
            clean_folder(input_dir)
        return out_path


def clean_folder(folder):
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print('删除失败 %s. 原因: %s' % (file_path, e))
if __name__ == "__main__":
    pre = Predictor()
    #初始化
    pre.setup()
    img = r"D:\Github\20240708Move_video_2\source_file\thumbnail.jpg"
    pre.predict(image = img)