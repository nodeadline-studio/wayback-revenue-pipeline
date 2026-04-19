import os
import logging
import boto3 # Standard for S3/R2
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class Storage:
    def __init__(self):
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        self.r2_bucket = os.getenv("R2_BUCKET_NAME")
        self.r2_account_id = os.getenv("R2_ACCOUNT_ID")
        self.r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_public_domain = os.getenv("R2_PUBLIC_DOMAIN") # e.g. https://reports.bizspy.ai

        self.use_r2 = all([self.r2_bucket, self.r2_account_id, self.r2_access_key, self.r2_secret_key])
        
        if self.use_r2:
            logger.info(f"Storage: Using Cloudflare R2 (Bucket: {self.r2_bucket})")
            self.s3_client = boto3.client(
                service_name='s3',
                endpoint_url=f'https://{self.r2_account_id}.r2.cloudflarestorage.com',
                aws_access_key_id=self.r2_access_key,
                aws_secret_access_key=self.r2_secret_key,
                region_name='auto' # R2 standard
            )
        else:
            logger.info("Storage: Using Local Filesystem")
            os.makedirs(self.output_dir, exist_ok=True)

    def save(self, content, relative_path, content_type='text/html'):
        """
        Saves content to storage.
        relative_path: e.g. 'bizspy-ai/report.html'
        """
        if self.use_r2:
            try:
                self.s3_client.put_object(
                    Bucket=self.r2_bucket,
                    Key=relative_path,
                    Body=content,
                    ContentType=content_type
                )
                url = f"{self.r2_public_domain}/{relative_path}" if self.r2_public_domain else f"R2://{relative_path}"
                return url
            except ClientError as e:
                logger.error(f"R2 Upload Failed: {e}")
                raise
        else:
            abs_path = os.path.join(self.output_dir, relative_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w") as f:
                f.write(content)
            return f"/reports/{relative_path}" # Relative URL for local serving

    def get_url(self, relative_path):
        if self.use_r2:
            return f"{self.r2_public_domain}/{relative_path}" if self.r2_public_domain else f"R2://{relative_path}"
        return f"/reports/{relative_path}"
