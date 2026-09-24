import time
import logging
from pathlib import Path
from huggingface_hub import list_repo_files, hf_hub_download

# ==========================================
# GLOBAL PATH CONFIGURATION
# ==========================================
# Dynamically resolve the absolute path to ONE LEVEL ABOVE the directory containing this script[cite: 1]
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Construct production-grade paths relative to the project root[cite: 1]
OUTPUT_DIR = PROJECT_ROOT / "dataset" / "standalone" / "invoices"

# ==========================================
# DOWNLOAD CONSTANTS
# ==========================================
REPO_ID = "Azzindani/Invoices_Data"
MAX_DOWNLOADS = 480
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

# Exponential Backoff Configuration
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 2
BACKOFF_FACTOR = 2.0

# Configure structured logging[cite: 1]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DatasetDownloader")

def _download_with_exponential_backoff(repo_id: str, filename: str, output_dir: Path) -> str | None:
    """
    Executes the Hugging Face download wrapped in an exponential backoff loop
    to handle transient network errors gracefully.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Requesting '{filename}' (Attempt {attempt}/{MAX_RETRIES})...")
            file_path = hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                filename=filename,
                local_dir=output_dir,
            )
            return file_path

        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.error(
                    f"Final retry limit reached ({MAX_RETRIES}). Download failed for '{filename}': {exc}",
                    exc_info=True
                )
                return None

            sleep_duration = BASE_DELAY_SECONDS * (BACKOFF_FACTOR ** (attempt - 1))
            logger.warning(
                f"Download failed on attempt {attempt}: {exc}. "
                f"Applying exponential backoff. Retrying in {sleep_duration:.2f}s..."
            )
            time.sleep(sleep_duration)

    return None

def download_invoices():
    """
    Retrieves up to 20 files from the specified Hugging Face repository 
    and saves them to the local production path.
    """
    try:
        # Ensure the dynamic path is created if it does not exist[cite: 1]
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Target directory verified at: {OUTPUT_DIR}")

        logger.info(f"Connecting to Hugging Face to list files for repo: {REPO_ID}...")
        try:
            files = list_repo_files(
                repo_id=REPO_ID,
                repo_type="dataset",
            )
        except Exception as e:
            logger.critical(f"Failed to fetch file list from repository '{REPO_ID}': {e}", exc_info=True)
            return

        # Filter for standard document formats (PDFs and images)
        document_files = [
            f for f in files
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
        ][:MAX_DOWNLOADS]

        total_files = len(document_files)
        if total_files == 0:
            logger.warning(f"No matching files found in repository {REPO_ID}.")
            return

        logger.info(f"Limiting download queue to {total_files} files.")
        successful_downloads = 0

        for index, file in enumerate(document_files, start=1):
            border = "=" * 70
            print(f"\n{border}")
            print(f"[{index}/{total_files}] DOWNLOADING: {file}")
            print(f"{border}\n")

            # Utilize backoff logic to prevent network-related crashes
            downloaded_path = _download_with_exponential_backoff(
                repo_id=REPO_ID, 
                filename=file, 
                output_dir=OUTPUT_DIR
            )

            if downloaded_path:
                successful_downloads += 1
                logger.info(f"Successfully saved to: {downloaded_path}")
            else:
                logger.warning(f"FAILED TO DOWNLOAD: {file}")

        print(f"\n{'=' * 70}")
        print(f"BATCH COMPLETE: {successful_downloads}/{total_files} files successfully retrieved.")
        print(f"{'=' * 70}\n")

    except Exception as batch_err:
        # Critical catch to prevent overall script crash[cite: 1]
        logger.critical(f"Critical failure during the download process: {batch_err}", exc_info=True)


if __name__ == "__main__":
    download_invoices()