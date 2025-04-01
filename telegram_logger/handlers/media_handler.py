import logging
import os
from contextlib import contextmanager, asynccontextmanager
from telethon.tl.types import Message as TelethonMessage
# Import necessary functions from utils.media
from telegram_logger.utils.media import (
    save_media_as_file,
    retrieve_media_as_file,
    _get_filename,
)

logger = logging.getLogger(__name__)

class RestrictedMediaHandler:
    def __init__(self, client):
        self.client = client
        logger.info("RestrictedMediaHandler initialized.")

    @asynccontextmanager
    async def prepare_media(self, message: TelethonMessage):
        """
        Downloads, decrypts (if needed), and yields the media file handle.
        Handles cleanup automatically via async context manager.
        """
        file_path = None
        media_file = None
        try:
            # Save the media (downloads and potentially decrypts based on save_media_as_file logic)
            file_path = await save_media_as_file(self.client, message)
            if not file_path:
                raise ValueError("Failed to save media file.")

            original_filename = _get_filename(message.media) or "restricted_media"
            logger.info(f"Restricted media saved to {file_path}. Original filename: {original_filename}")

            # Retrieve the (potentially decrypted) file handle
            # retrieve_media_as_file should return a context manager itself
            with retrieve_media_as_file(file_path, is_restricted=True) as media_f: # Assuming retrieve handles decryption context
                 if not media_f:
                     raise ValueError(f"Failed to retrieve/decrypt media from {file_path}")
                 # Set the desired filename for sending
                 try:
                     # Try setting name directly on the file object if possible/needed by Telethon
                     media_f.name = original_filename
                 except AttributeError:
                     logger.warning(f"Could not set name attribute on file object for {original_filename}")
                     # Telethon might handle filename differently, often via `attributes` parameter in send_file

                 logger.info(f"Yielding decrypted file handle: {original_filename}")
                 yield media_f # Yield the file handle within the context
                 media_file = media_f # Keep track for logging success

        except Exception as e:
            logger.error(f"Error preparing restricted media: {e}", exc_info=True)
            # Re-raise or handle as needed by the caller; here we let the context manager exit
            raise # Reraise the exception so the caller knows preparation failed
        finally:
            # Cleanup: retrieve_media_as_file's context should handle closing the file.
            # Optional: Delete the temporary downloaded/encrypted file
            # if file_path and os.path.exists(file_path):
            #     try:
            #         os.remove(file_path)
            #         logger.debug(f"Cleaned up temporary file: {file_path}")
            #     except OSError as e_clean:
            #         logger.error(f"Failed to clean up temporary file {file_path}: {e_clean}")
            if media_file:
                 logger.info(f"Finished processing media: {getattr(media_file, 'name', 'unknown')}")
            else:
                 logger.warning(f"Media preparation context finished, but no media file was yielded successfully (likely due to an error).")
