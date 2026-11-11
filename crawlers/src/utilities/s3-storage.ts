import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

const s3 = new S3Client({ region: process.env.AWS_REGION ?? "eu-west-2" });

export type EventPhase = "past" | "today" | "future";

export type DataKind = "racecards" | "races";

export const generateS3FileName = (
  phase: EventPhase,
  kind: DataKind,
  date: string,
  name: string,
  daysAhead: number
): string => {
  const suffix = phase === "future" ? `-t-${daysAhead}` : "";
  return `${phase}/${kind}/date=${date}/${name}${suffix}.json`;
};

export const saveJsonToS3 = async (
  key: string,
  data: unknown
): Promise<void> => {
  const bucket = process.env.S3_BUCKET;
  if (!bucket) {
    throw new Error("S3_BUCKET environment variable is not set");
  }

  await s3.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: JSON.stringify(data),
      ContentType: "application/json"
    })
  );

  console.log(`Saved s3://${bucket}/${key}`);
};
