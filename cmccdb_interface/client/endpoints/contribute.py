# import flask
# import os
# from flask import request, redirect, url_for


# app = flask.Flask(__name__)

# UPLOAD_FOLDER = ('/home/coder/cmccdb-interface/ord_interface/client/endpoints/UPLOAD_FOLDER')
# ALLOWED_EXTENSIONS = {'xlsx', 'csv'}

# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# def allowed_file(filename):
   
#     return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# @app.route('/api/contribute', methods=['POST'])
# def contribute():
     
#     if 'file' not in request.files:
#         return 'No file part', 400

#     file = request.files['file']
    
   
#     if file.filename == '':
#         return 'No selected file', 400

   
#     if not is_valid_filename(file.filename):
#         return 'Invalid filename', 400

    
#     if file and allowed_file(file.filename):
        
#         filename = file.filename

        
#         file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#         file.save(file_path)

#         try:
            
#             user = request.form.get('--name', 'Web_uploader')
#             email = request.form.get('--email', 'maboyer@tamu.edu')

            
           

#         except Exception as e:
#             return str(e), 500

    
#         return redirect('/browse')

#     return 'File type not allowed', 400

# @app.route('/contribute', methods=['POST'])
# def upload():
#     if 'file' not in request.files:
#         return redirect(request.url)
#     file = request.files['file']
#     if file and allowed_file(file.filename):
#         filename = secure_filename(file.filename)
#         file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#         file.save(file_path)

        
#         pptx_filename = filename.rsplit('.', 1)[0] + '.pptx'
#         pptx_path = os.path.join(app.config['UPLOAD_FOLDER'], pptx_filename)
#         convert_xlsx_to_pptx(file_path, pptx_path)

        
#         return redirect(url_for('download_file', filename=pptx_filename))
#     else:
#         return "File type not allowed", 400

# @app.route('/contribute/<filename>')
# def download_file(filename):
#     return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# if __name__ == "__main__":
    
#     if not os.path.exists(UPLOAD_FOLDER):
#         os.makedirs(UPLOAD_FOLDER)
#     app.run(debug=True)