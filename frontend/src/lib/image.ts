/** A smaller copy of a picture, so a phone photo uploads quickly; the original is returned when it cannot be shrunk here. */
export async function shrinkImage(file: File, longest = 1280): Promise<File> {
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, longest / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, 'image/jpeg', 0.8))
    return blob && blob.size < file.size ? new File([blob], 'picture.jpg', { type: 'image/jpeg' }) : file
  } catch {
    return file
  }
}
