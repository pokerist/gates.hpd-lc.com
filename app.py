import os
import uuid
import numpy as np
import cv2
from flask import Flask, render_template, request, jsonify
from PIL import Image
from ultralytics import YOLO
import easyocr
import pytesseract
import logging
from datetime import datetime
from models import db, Person, Entry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gates_hyde_park.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Color scheme for different regions
COLORS = {
    'id_card': (255, 0, 0),      # Blue for ID card outline
    'firstName': (0, 255, 0),    # Green for first name
    'lastName': (0, 255, 255),   # Yellow for last name
    'address': (255, 255, 0),    # Orange for address
    'serial': (255, 0, 255),     # Purple for serial
    'nid': (0, 0, 255),          # Red for national ID
    'digit': (128, 128, 128)     # Gray for individual digits
}

class IDCardProcessor:
    def __init__(self):
        self.models = {}
        self.ocr_reader = None
        self.load_models()
        self.load_ocr()
    
    def load_models(self):
        """Load all YOLO models once at startup"""
        try:
            logger.info("Loading YOLO models...")
            self.models['id_card'] = YOLO('yolo/detect_id_card.pt')
            self.models['fields'] = YOLO('yolo/detect_odjects.pt')
            logger.info("All models loaded successfully")
        except Exception as e:
            logger.error(f"Error loading models: {e}")
            raise
    
    def load_ocr(self):
        """Load OCR engines"""
        try:
            logger.info("Loading OCR engines...")
            # Initialize EasyOCR for Arabic text
            self.ocr_reader = easyocr.Reader(['ar'])
            logger.info("OCR engines loaded successfully")
        except Exception as e:
            logger.error(f"Error loading OCR: {e}")
            raise
    
    def draw_bounding_box(self, image, box, label, color, thickness=2):
        """Draw a bounding box with label on the image"""
        x1, y1, x2, y2 = map(int, box)
        
        # Draw rectangle
        cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
        
        # Draw label background
        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
        cv2.rectangle(image, (x1, y1 - 20), (x1 + label_size[0], y1), color, -1)
        
        # Draw label text
        cv2.putText(image, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 
                   0.6, (255, 255, 255), 2)
        
        return image
    
    def enhance_image(self, image):
        """Enhance image by correcting skew and rotation"""
        try:
            # Convert to grayscale for skew detection
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Apply Gaussian blur to reduce noise
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Use Canny edge detection
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            
            # Detect lines using Hough Transform
            lines = cv2.HoughLines(edges, 1, np.pi / 180, 100)
            
            if lines is not None:
                angles = []
                for line in lines[:10]:  # Check first 10 lines
                    rho, theta = line[0]
                    angle = np.degrees(theta)
                    
                    # Normalize angle to -45 to 45 degrees
                    if angle > 45:
                        angle -= 90
                    elif angle < -45:
                        angle += 90
                    
                    angles.append(angle)
                
                if angles:
                    # Calculate median angle for more robust estimation
                    median_angle = np.median(angles)
                    
                    # Only rotate if angle is significant (greater than 1 degree)
                    if abs(median_angle) > 1.0:
                        # Rotate image to correct skew
                        (h, w) = image.shape[:2]
                        center = (w // 2, h // 2)
                        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
                        rotated = cv2.warpAffine(image, M, (w, h), 
                                               flags=cv2.INTER_CUBIC, 
                                               borderMode=cv2.BORDER_REPLICATE)
                        return rotated
            
            # If no significant skew detected, return original image
            return image
            
        except Exception as e:
            logger.warning(f"Image enhancement failed: {e}")
            return image
    
    def preprocess_for_ocr(self, image):
        """Preprocess image for better OCR accuracy"""
        try:
            # Convert to grayscale if color
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()
            
            # Apply Gaussian blur to reduce noise
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            
            # Apply threshold to create binary image
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Optional: Apply morphological operations to enhance text
            kernel = np.ones((2,2), np.uint8)
            binary = cv2.dilate(binary, kernel, iterations=1)
            binary = cv2.erode(binary, kernel, iterations=1)
            
            return binary
            
        except Exception as e:
            logger.warning(f"OCR preprocessing failed: {e}")
            return image
    
    def extract_text_easyocr(self, image):
        """Extract text using EasyOCR"""
        try:
            # Preprocess image for better OCR
            processed_image = self.preprocess_for_ocr(image)
            
            # Extract text
            results = self.ocr_reader.readtext(processed_image)
            
            if results:
                # Get the most confident result
                text = results[0][1]
                confidence = results[0][2]
                return text.strip(), confidence
            else:
                return "", 0.0
                
        except Exception as e:
            logger.warning(f"EasyOCR extraction failed: {e}")
            return "", 0.0
    
    def extract_text_tesseract(self, image):
        """Extract text using Tesseract (for digits)"""
        try:
            # Preprocess image for better OCR
            processed_image = self.preprocess_for_ocr(image)
            
            # Configure Tesseract for Arabic digits using ara_number model
            config = '--psm 6 --oem 3 -l ara_number'
            
            # Extract text
            text = pytesseract.image_to_string(processed_image, config=config)
            return text.strip()
            
        except Exception as e:
            logger.warning(f"Tesseract extraction failed: {e}")
            return ""

    def process_image(self, image_path):
        """Main processing pipeline"""
        try:
            # Load original image
            original_image = cv2.imread(image_path)
            if original_image is None:
                raise ValueError("Could not load image")
            
            # Enhance image by correcting skew and rotation
            enhanced_image = self.enhance_image(original_image)
            
            # Create copy for visualization
            result_image = enhanced_image.copy()
            detections = []
            
            # Stage 1: Detect ID card
            logger.info("Stage 1: Detecting ID card...")
            id_card_results = self.models['id_card'](original_image, conf=0.5)
            
            if not id_card_results[0].boxes:
                return result_image, detections, "No ID card detected in the image"
            
            # Get the most confident ID card detection
            id_card_box = id_card_results[0].boxes.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = map(int, id_card_box)
            
            # Draw ID card bounding box
            result_image = self.draw_bounding_box(
                result_image, id_card_box, "ID Card", COLORS['id_card'], 3
            )
            
            # Crop the ID card for further processing
            cropped_id = original_image[y1:y2, x1:x2]
            
            # Stage 2: Detect fields on cropped ID card
            logger.info("Stage 2: Detecting fields...")
            field_results = self.models['fields'](cropped_id, conf=0.5)
            
            if field_results[0].boxes:
                for box, cls in zip(field_results[0].boxes.xyxy, field_results[0].boxes.cls):
                    field_box = box.cpu().numpy()
                    class_id = int(cls.cpu().numpy())
                    class_name = field_results[0].names[class_id]
                    
                    # Adjust coordinates to original image space
                    adjusted_box = [
                        field_box[0] + x1,  # x1
                        field_box[1] + y1,  # y1
                        field_box[2] + x1,  # x2
                        field_box[3] + y1   # y2
                    ]
                    
                    detections.append({
                        'type': 'field',
                        'name': class_name,
                        'box': adjusted_box
                    })
                    
                    # Only draw bounding boxes for firstName, lastName, and nid
                    if class_name in ['firstName', 'lastName', 'nid']:
                        result_image = self.draw_bounding_box(
                            result_image, adjusted_box, class_name, COLORS.get(class_name, COLORS['digit'])
                        )
                    
                    # Stage 3: Extract text from fields using OCR
                    if class_name in ['firstName', 'lastName']:
                        logger.info(f"Stage 3: Extracting {class_name} text...")
                        field_cropped = cropped_id[
                            int(field_box[1]):int(field_box[3]),
                            int(field_box[0]):int(field_box[2])
                        ]
                        
                        # Extract text using EasyOCR
                        extracted_text, confidence = self.extract_text_easyocr(field_cropped)
                        
                        if extracted_text:
                            detections.append({
                                'type': 'extracted_text',
                                'name': class_name,
                                'text': extracted_text,
                                'confidence': confidence
                            })
                    
                    elif class_name == 'nid':
                        logger.info("Stage 3: Extracting national ID text...")
                        nid_cropped = cropped_id[
                            int(field_box[1]):int(field_box[3]),
                            int(field_box[0]):int(field_box[2])
                        ]
                        
                        # Extract text using Tesseract for digits
                        extracted_id = self.extract_text_tesseract(nid_cropped)
                        
                        if extracted_id:
                            detections.append({
                                'type': 'extracted_text',
                                'name': 'national_id',
                                'text': extracted_id,
                                'confidence': 1.0  # Tesseract doesn't provide confidence easily
                            })
            
            return result_image, detections, "Processing completed successfully"
            
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            return original_image, [], f"Error processing image: {str(e)}"

# Initialize processor
processor = IDCardProcessor()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/security')
def security():
    return render_template('security.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/api/verify', methods=['POST'])
def verify_id():
    """API endpoint for ID verification"""
    try:
        # Get image data from request
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Generate unique filename
        filename = str(uuid.uuid4()) + '.jpg'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Save uploaded file
        file.save(filepath)
        
        # Process image
        result_image, detections, message = processor.process_image(filepath)
        
        # Extract text results
        first_name = ''
        last_name = ''
        national_id = ''
        first_name_confidence = 0
        last_name_confidence = 0
        
        for detection in detections:
            if detection['type'] == 'extracted_text':
                if detection['name'] == 'firstName':
                    first_name = detection['text']
                    first_name_confidence = detection['confidence']
                elif detection['name'] == 'lastName':
                    last_name = detection['text']
                    last_name_confidence = detection['confidence']
                elif detection['name'] == 'national_id':
                    national_id = detection['text']
        
        # Clean up uploaded file
        os.remove(filepath)
        
        # Validate extracted data
        if not first_name or not last_name:
            return jsonify({
                'status': 'error',
                'message': '❓ Retake photo — Name not clear',
                'details': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'national_id': national_id
                }
            })
        
        if not national_id or not national_id.isdigit() or len(national_id) != 14:
            return jsonify({
                'status': 'error',
                'message': '❓ Retake photo — ID not clear',
                'details': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'national_id': national_id
                }
            })
        
        # Combine names
        full_name = f"{first_name} {last_name}".strip()
        
        # Check database for existing person
        person = Person.query.filter_by(national_id=national_id).first()
        
        if not person:
            # New person - auto-insert
            person = Person(
                name=full_name,
                national_id=national_id,
                blocked=False,
                block_reason="قرار إداري"
            )
            db.session.add(person)
            db.session.commit()
            
            # Log entry
            entry = Entry(
                name=full_name,
                national_id=national_id,
                status='Welcome'
            )
            db.session.add(entry)
            db.session.commit()
            
            return jsonify({
                'status': 'success',
                'message': f'✓ Welcome {full_name}',
                'details': {
                    'name': full_name,
                    'national_id': national_id,
                    'action': 'new_person_added'
                }
            })
        
        else:
            # Existing person
            if person.blocked:
                # Blocked person - no entry logged
                return jsonify({
                    'status': 'blocked',
                    'message': f'⚠️ ACCESS DENIED\n{person.name} (ID: {national_id}) is BLOCKED\nReason: {person.block_reason}',
                    'details': {
                        'name': person.name,
                        'national_id': national_id,
                        'block_reason': person.block_reason
                    }
                })
            else:
                # Not blocked - log entry and grant access
                entry = Entry(
                    name=person.name,
                    national_id=person.national_id,
                    status='Access Granted'
                )
                db.session.add(entry)
                db.session.commit()
                
                return jsonify({
                    'status': 'success',
                    'message': f'✓ Access granted',
                    'details': {
                        'name': person.name,
                        'national_id': person.national_id,
                        'action': 'access_granted'
                    }
                })
        
    except Exception as e:
        logger.error(f"Verification error: {e}")
        return jsonify({'error': f'Verification failed: {str(e)}'}), 500

@app.route('/api/people')
def get_people():
    """Get all people with their status"""
    try:
        people = Person.query.all()
        result = []
        for person in people:
            # Get latest entry for this person
            latest_entry = Entry.query.filter_by(national_id=person.national_id).order_by(Entry.timestamp.desc()).first()
            last_seen = latest_entry.timestamp if latest_entry else person.created_at
            
            result.append({
                'id': person.id,
                'name': person.name,
                'national_id': person.national_id,
                'blocked': person.blocked,
                'block_reason': person.block_reason,
                'last_seen': last_seen.strftime('%Y-%m-%d %H:%M:%S')
            })
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting people: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/entries')
def get_entries():
    """Get all entries"""
    try:
        entries = Entry.query.order_by(Entry.timestamp.desc()).limit(100).all()
        result = []
        for entry in entries:
            result.append({
                'id': entry.id,
                'name': entry.name,
                'national_id': entry.national_id,
                'status': entry.status,
                'timestamp': entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            })
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting entries: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search')
def search():
    """Search people by name or national ID"""
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify([])
        
        # Search by name or national ID
        people = Person.query.filter(
            (Person.name.contains(query)) | 
            (Person.national_id.contains(query))
        ).all()
        
        result = []
        for person in people:
            # Get latest entry for this person
            latest_entry = Entry.query.filter_by(national_id=person.national_id).order_by(Entry.timestamp.desc()).first()
            last_seen = latest_entry.timestamp if latest_entry else person.created_at
            
            result.append({
                'id': person.id,
                'name': person.name,
                'national_id': person.national_id,
                'blocked': person.blocked,
                'block_reason': person.block_reason,
                'last_seen': last_seen.strftime('%Y-%m-%d %H:%M:%S')
            })
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error searching: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/toggle-block/<int:person_id>', methods=['POST'])
def toggle_block(person_id):
    """Toggle block status for a person"""
    try:
        person = Person.query.get_or_404(person_id)
        data = request.get_json()
        
        person.blocked = not person.blocked
        if person.blocked:
            person.block_reason = data.get('reason', 'قرار إداري')
        else:
            person.block_reason = 'قرار إداري'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'blocked': person.blocked,
            'block_reason': person.block_reason
        })
    except Exception as e:
        logger.error(f"Error toggling block: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

from flask import send_from_directory

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)