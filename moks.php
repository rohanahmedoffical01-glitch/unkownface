<?php
if (isset($_GET['gete'])) {
    $filePath = $_GET['gete'];

    $content = file_get_contents($filePath);
    $lines = explode("\n", $content);
    $lines = array_filter($lines, 'trim');
    $jsonData = json_encode($lines);
    header('Content-Type: application/json');
    echo $jsonData;
} else {
    echo "Huh Gay?";
}
?>
