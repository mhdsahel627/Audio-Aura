from cloudinary_storage.storage import MediaCloudinaryStorage
import cloudinary

class VideoCloudinaryStorage(MediaCloudinaryStorage):
    """Custom storage for video files with video resource type"""
    
    def _upload(self, name, content):
        """Override upload to force video resource type"""
        # Extract folder from name
        folder = '/'.join(name.split('/')[:-1]) if '/' in name else ''
        
        options = {
            'resource_type': 'video',  # Force video type
            'folder': folder or 'media/banners/videos',
            'use_filename': True,
            'unique_filename': True,
        }
        
        # Upload using cloudinary uploader
        response = cloudinary.uploader.upload(content, **options)
        return response
    
    def url(self, name):
        """Override URL generation to use video path"""
        # Get the standard URL
        url = super().url(name)
        
        # Replace /image/ with /video/ in the URL
        if '/image/upload/' in url:
            url = url.replace('/image/upload/', '/video/upload/')
        
        return url
