import os
def split_file(file_path, chunk_size, output_dir, encoding='utf-8'):
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 打开原始文件
    with open(file_path, 'r', encoding=encoding) as file:
        # 读取文件内容
        while True:
            # 读取chunk_size大小的数据
            chunk = file.read(chunk_size)
            # 如果读取的数据为空，表示文件已经读完，退出循环
            if not chunk:
                break
            # 分割文件的序号
            chunk_number = len(os.listdir(output_dir)) + 1
            # 分割文件的文件名
            chunk_file_path = os.path.join(output_dir, f'part_{chunk_number}.txt')
            # 写入分割出的数据到新文件
            with open(chunk_file_path, 'w', encoding=encoding) as chunk_file:
                chunk_file.write(chunk)

# 设置原始文件路径
file_path = 'output.txt'
# 设置每个子文件的大小，这里是2MB
chunk_size = 2 * 1024 * 680
# 设置输出目录
output_dir = '子文件'

# 调用函数进行文件分割
split_file(file_path, chunk_size, output_dir)

