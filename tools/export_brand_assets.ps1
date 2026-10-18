# Export the current raster artwork without changing its design.
# Windows PowerShell 5.1; uses only the Windows drawing library.
param([string]$BrandDirectory = (Join-Path $PSScriptRoot '..\apps\web\brand'))
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$brand=[IO.Path]::GetFullPath($BrandDirectory)

function Export-SizedImage([string]$Source, [int]$Size, [string]$Destination) {
    $sourceImage=[Drawing.Image]::FromFile($Source)
    $bitmap=[Drawing.Bitmap]::new($Size,$Size,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics=[Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.Clear([Drawing.Color]::Transparent)
        $graphics.CompositingMode=[Drawing.Drawing2D.CompositingMode]::SourceCopy
        $graphics.InterpolationMode=[Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode=[Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.DrawImage($sourceImage,0,0,$Size,$Size)
        $bitmap.Save($Destination,[Drawing.Imaging.ImageFormat]::Png)
    } finally { $graphics.Dispose(); $bitmap.Dispose(); $sourceImage.Dispose() }
}

foreach ($name in @('core')) {
    Export-SizedImage (Join-Path $brand "source\$name.png") 512 (Join-Path $brand "$name.png")
}
Export-SizedImage (Join-Path $brand 'source\core.png') 256 (Join-Path $brand 'icon.png')

$sizes=@(16,24,32,48,64,128,256)
$frames=@()
foreach ($size in $sizes) {
    $destination=Join-Path $brand "icon-$size.png"
    Export-SizedImage (Join-Path $brand 'source\core.png') $size $destination
    $frames+=,@([IO.File]::ReadAllBytes($destination))
}
$writer=[IO.BinaryWriter]::new([IO.File]::Create((Join-Path $brand 'jarvis.ico')))
try {
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$sizes.Count)
    $offset=6+16*$sizes.Count
    for ($i=0; $i -lt $sizes.Count; $i++) {
        $side=if ($sizes[$i] -eq 256) { 0 } else { $sizes[$i] }
        $writer.Write([byte]$side); $writer.Write([byte]$side); $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32)
        $writer.Write([uint32]$frames[$i].Length); $writer.Write([uint32]$offset)
        $offset+=$frames[$i].Length
    }
    foreach ($frame in $frames) { $writer.Write([byte[]]$frame) }
} finally { $writer.Dispose() }
Write-Output 'Exported core, PNG icon sizes and seven-frame jarvis.ico.'
