# Render generated brand assets from the same code-native source used by the tray.
param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\apps\tray\assets'))
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing,System.Net.Http,System.Web.Extensions
Add-Type -Path (Join-Path $PSScriptRoot '..\apps\tray\TrayApplication.cs') -ReferencedAssemblies System.Windows.Forms,System.Drawing,System.Net.Http,System.Web.Extensions
$output=[IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($output) | Out-Null
$sizes=@(16,24,32,48,64,128,256)
$frames=@()
foreach ($size in $sizes) {
    $bitmap=[Jarvis.TrayApplication]::DrawIcon($size,'standby')
    $stream=[IO.MemoryStream]::new()
    try {
        $bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
        $frames+=,@($stream.ToArray())
    } finally { $bitmap.Dispose(); $stream.Dispose() }
}
$file=[IO.File]::Create((Join-Path $output 'jarvis.ico'))
$writer=[IO.BinaryWriter]::new($file)
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
} finally { $writer.Dispose(); $file.Dispose() }
$preview=[Drawing.Bitmap]::new(680,240)
$graphics=[Drawing.Graphics]::FromImage($preview)
$font=[Drawing.Font]::new('Segoe UI',11)
try {
    $graphics.Clear([Drawing.Color]::FromArgb(242,245,249))
    $states=@('standby','working','needs_attention','offline')
    for ($i=0; $i -lt $states.Count; $i++) {
        $bitmap=[Jarvis.TrayApplication]::DrawIcon(72,$states[$i])
        try { $graphics.DrawImageUnscaled($bitmap,30+165*$i,20) } finally { $bitmap.Dispose() }
        $graphics.DrawString($states[$i],$font,[Drawing.Brushes]::Black,22+165*$i,100)
    }
    $x=30
    foreach ($size in @(16,24,32,48,64)) {
        $bitmap=[Jarvis.TrayApplication]::DrawIcon($size,'standby')
        try { $graphics.DrawImageUnscaled($bitmap,$x,185-$size) } finally { $bitmap.Dispose() }
        $graphics.DrawString(($size.ToString()+' px'),$font,[Drawing.Brushes]::Black,$x,198)
        $x+=120
    }
    $preview.Save((Join-Path $output 'preview.png'),[Drawing.Imaging.ImageFormat]::Png)
} finally { $font.Dispose(); $graphics.Dispose(); $preview.Dispose() }
Write-Output "Generated jarvis.ico and preview.png in $output"
