import time
import logging
from pathlib import Path
from PIL import Image

# ==========================================
# GLOBAL PATH CONFIGURATION
# ==========================================
# Dynamically resolve the absolute path to ONE LEVEL ABOVE the directory containing this script
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Construct production-grade paths relative to the project root
OUTPUT_DIR = PROJECT_ROOT / "dataset" / "standalone" / "receipts"

# ==========================================
# DOWNLOAD CONSTANTS
# ==========================================
REPO_ID = "jsdnrs/ICDAR2019-SROIE"
MAX_DOWNLOADS = 480

# Exponential Backoff Configuration
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 2
BACKOFF_FACTOR = 2.0

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ReceiptExtractor")


def _load_dataset_with_backoff(repo_id: str):
    """
    Loads the Hugging Face dataset with an exponential backoff loop 
    to handle transient connection interruptions.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        logger.critical(
            "The 'datasets' package is required to parse Parquet-backed vision data. "
            "Please run: pip install datasets",
            exc_info=True
        )
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Connecting to Hugging Face to load '{repo_id}' (Attempt {attempt}/{MAX_RETRIES})...")
            dataset = load_dataset(repo_id)
            logger.info(f"Successfully loaded dataset structure for '{repo_id}'.")
            return dataset

        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.error(
                    f"Final retry limit reached ({MAX_RETRIES}). Failed to load repository '{repo_id}': {exc}",
                    exc_info=True
                )
                return None

            sleep_duration = BASE_DELAY_SECONDS * (BACKOFF_FACTOR ** (attempt - 1))
            logger.warning(
                f"Failed to load dataset: {exc}. "
                f"Applying exponential backoff. Retrying in {sleep_duration:.2f}s..."
            )
            time.sleep(sleep_duration)

    return None


def download_and_extract_receipts():
    """
    Extracts up to 480 receipt images from the Parquet records
    and persists them as individual JPEG files.
    """
    try:
        # Ensure output directory exists
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Target directory verified at: {OUTPUT_DIR}")

        dataset = _load_dataset_with_backoff(REPO_ID)
        if dataset is None:
            logger.error("Dataset provisioning failed. Terminating extraction.")
            return

        saved_count = 0

        # Iterate over available dataset splits (e.g., train, test)
        for split_name in dataset.keys():
            if saved_count >= MAX_DOWNLOADS:
                break

            split_data = dataset[split_name]
            total_split_items = len(split_data)
            logger.info(f"Processing split '{split_name}' ({total_split_items} items available)...")

            for idx, record in enumerate(split_data, start=1):
                if saved_count >= MAX_DOWNLOADS:
                    break

                try:
                    img_data = record.get("image")
                    if not img_data:
                        continue

                    # Extract existing identifier or fall back to an indexed name
                    record_id = record.get("id") or record.get("filename")
                    if record_id:
                        clean_stem = Path(str(record_id)).stem
                        filename = f"{clean_stem}.jpg"
                    else:
                        filename = f"receipt_{saved_count + 1:04d}.jpg"

                    destination_path = OUTPUT_DIR / filename

                    # Convert and save PIL Image to standard RGB JPEG
                    if isinstance(img_data, Image.Image):
                        rgb_image = img_data.convert("RGB")
                        rgb_image.save(destination_path, format="JPEG", quality=95)
                    else:
                        logger.warning(f"Skipping record {idx}: image is not a valid PIL Image instance.")
                        continue

                    saved_count += 1

                    if saved_count % 50 == 0 or saved_count == MAX_DOWNLOADS:
                        logger.info(f"Progress: [{saved_count}/{MAX_DOWNLOADS}] receipts written to disk.")

                except Exception as item_err:
                    logger.error(f"Failed to process record {idx} in split '{split_name}': {item_err}")
                    continue

        border = "=" * 70
        print(f"\n{border}")
        print(f"BATCH COMPLETE: {saved_count}/{MAX_DOWNLOADS} receipt images extracted.")
        print(f"Saved to: {OUTPUT_DIR.resolve()}")
        print(f"{border}\n")

    except Exception as general_err:
        logger.critical(f"Critical failure during receipt extraction: {general_err}", exc_info=True)


if __name__ == "__main__":
    download_and_extract_receipts()