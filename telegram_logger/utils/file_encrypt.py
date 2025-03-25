import io
from os import stat
from contextlib import contextmanager
import pyAesCrypt
from telegram_logger.config import FILE_PASSWORD

BUFFER_SIZE = 1024 * 1024

# this is meant to be more about obfuscation and less about security


@contextmanager
def encrypted(file_path, password=FILE_PASSWORD):
    tmp_file = io.BytesIO()
    try:
        yield tmp_file
    finally:
        tmp_file.seek(0)
        with open(file_path, 'wb') as f_out:
            pyAesCrypt.encryptStream(
                tmp_file, f_out, password, bufferSize=BUFFER_SIZE)
        tmp_file.close()


@contextmanager
def decrypted(file_path, password=FILE_PASSWORD):
    tmp_file = io.BytesIO()
    try:
        with open(file_path, 'rb') as f_in:
            pyAesCrypt.decryptStream(
                f_in, tmp_file, password, bufferSize=BUFFER_SIZE, inputLength=stat(file_path).st_size)
        tmp_file.seek(0)
        yield tmp_file
    finally:
        tmp_file.close()
