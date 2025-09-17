<?php
$uploadDirectory = 'uploads/';

if (!is_dir($uploadDirectory)) {
    mkdir($uploadDirectory, 0777, true);
}

ini_set('post_max_size', '100M');
ini_set('upload_max_filesize', '100M');
ini_set('max_execution_time', 300); // 5 minutes
ini_set('memory_limit', '256M');

if ($_FILES['file']['error'] === UPLOAD_ERR_OK) {
    $filename = uniqid() . '_' . $_FILES['file']['name'];
    move_uploaded_file($_FILES['file']['tmp_name'], $uploadDirectory . $filename);

    $protocol = isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] === 'on' ? 'https' : 'http';
    $downloadLink = $protocol . '://' . $_SERVER['HTTP_HOST'] . '/' . $uploadDirectory . $filename;

    echo $downloadLink;
} else {
    echo 'Error uploading file. Error code: ' . $_FILES['file']['error'];
}
?>
