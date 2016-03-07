#!/usr/bin/env python

import argparse, time
import numpy as np
import tensorflow as tf
from nltk.translate.bleu_score import bleu
from termcolor import colored

from image_encoder import ImageEncoder
from decoder import Decoder
from vocabulary import Vocabulary

def log(message):
    print "{}: {}".format(colored(time.strftime("%Y-%m-%d %H:%M:%S"), 'yellow'), message)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Trains the image captioning.')
    parser.add_argument("--train-images", type=argparse.FileType('rb'),
                        help="File with training images features", required=True)
    parser.add_argument("--valid-images", type=argparse.FileType('rb'),
                        help="File with validation images features.", required=True)
    parser.add_argument("--tokenized-train-text", type=argparse.FileType('r'),
                        help="File with tokenized training target sentences.", required=True)
    parser.add_argument("--tokenized-valid-text", type=argparse.FileType('r'), required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--maximum-output", type=int, default=20)
    parser.add_argument("--use-attention", type=bool, default=True)
    parser.add_argument("--embeddings-size", type=int, default=256)
    parser.add_argument("--scheduled-sampling", type=float, default=None)
    parser.add_argument("--epochs", type=int, default=10)
    args = parser.parse_args()

    print colored("=========================================================", 'green')
    print colored("TRAINING THE IMAGE CAPTIONING ONLY", 'green')
    print colored("=========================================================", 'green')

    print ""
    for arg in vars(args):
        value = str(getattr(args, arg))
        dots_count = 78 - len(arg) - len(value)
        print "{} {} {}".format(arg, "".join(['.' for _ in range(dots_count)]), value)
    print ""

    log("The training script started")
    training_images = np.load(args.train_images)
    args.train_images.close()
    log("Loaded training images.")
    validation_images = np.load(args.valid_images)
    args.valid_images.close()
    log("Loaded validation images.")

    training_sentences = [l.rstrip().split(" ") for l in args.tokenized_train_text][:len(training_images)]
    log("Loaded {} training sentences.".format(len(training_sentences)))
    validation_sentences = [l.rstrip().split(" ") for l in args.tokenized_valid_text][:len(validation_images)]
    log("Loaded {} validation sentences.".format(len(validation_sentences)))

    vocabulary = \
        Vocabulary(tokenized_text=[w for s in training_sentences for w in s])

    log("Training vocabulary has {} words".format(len(vocabulary)))

    log("Buiding the TensorFlow computation graph.")
    encoder = ImageEncoder()
    decoder = Decoder(encoder, vocabulary, embedding_size=args.embeddings_size,
            use_attention=args.use_attention, max_out_len=args.maximum_output, use_peepholes=True,
            scheduled_sampling=args.scheduled_sampling)

    def feed_dict(images, sentences, train=False):
        fd = {encoder.image_features: images}
        sentnces_tensors, weights_tensors = \
            vocabulary.sentences_to_tensor(sentences, args.maximum_output, train=train)
        for weight_plc, weight_tensor in zip(decoder.weights_ins, weights_tensors):
            fd[weight_plc] = weight_tensor

        for words_plc, words_tensor in zip(decoder.inputs, sentnces_tensors):
            fd[words_plc] = words_tensor
        return fd

    valid_feed_dict = feed_dict(validation_images, validation_sentences)
    optimize_op = tf.train.AdamOptimizer().minimize(decoder.cost)
    # gradients = optimizer.compute_gradients(cost)

    summary_train = tf.merge_summary(tf.get_collection("summary_train"))
    summary_test = tf.merge_summary(tf.get_collection("summary_test"))

    log("Initializing the TensorFlow session.")
    sess = tf.Session(config=tf.ConfigProto(inter_op_parallelism_threads=4,
                                            intra_op_parallelism_threads=4))
    sess.run(tf.initialize_all_variables())

    log("Starting training")
    step = 0
    for i in range(args.epochs):
        for start in range(0, len(training_sentences), args.batch_size):
            step += 1
            batch_feed_dict = feed_dict(training_images[start:start + args.batch_size],
                    training_sentences[start:start + args.batch_size], train=True)
            if step % 20 == 1:
                computation = sess.run([optimize_op, decoder.loss_with_decoded_ins, decoder.loss_with_gt_ins] \
                        + decoder.decoded_seq, feed_dict=batch_feed_dict)
                decoded_sentences = \
                    vocabulary.vectors_to_sentences(computation[-args.maximum_output - 1:])

                batch_sentences = training_sentences[start:start + args.batch_size]
                bleu_1 = \
                    100 * sum([bleu([ref], hyp, [1., 0., 0., 0.])
                            for ref, hyp in zip(batch_sentences, decoded_sentences)])/ args.batch_size
                bleu_4 = \
                    100 * sum([bleu([ref], hyp, [0.25, 0.25, 0.25, 0.25])
                            for ref, hyp in zip(batch_sentences, decoded_sentences)]) / args.batch_size

                print "opt. loss: {:.4f}    dec. loss: {:.4f}    BLEU-1: {:.2f}    BLEU-4: {:.2f}"\
                        .format(computation[2], computation[1], bleu_1, bleu_4)
            else:
                sess.run([optimize_op], feed_dict=batch_feed_dict)

            if step % 500 == 499:
                computation = sess.run([decoder.loss_with_decoded_ins, decoder.loss_with_gt_ins] \
                        + decoder.decoded_seq, feed_dict=valid_feed_dict)
                decoded_validation_sentences = \
                    vocabulary.vectors_to_sentences(computation[-args.maximum_output - 1:])

                validation_bleu_1 = \
                    100 * sum([bleu([ref], hyp, [1., 0., 0., 0.])
                            for ref, hyp in zip(validation_sentences, decoded_validation_sentences)]) / len(validation_sentences)
                validation_bleu_4 = \
                    100 * sum([bleu([ref], hyp, [0.25, 0.25, 0.25, 0.25])
                            for ref, hyp in zip(validation_sentences, decoded_validation_sentences)]) / len(validation_sentences)
                print ""
                print "Validation (epoch {}, batch start {}):".format(i, start)
                print "opt. loss: {:.4f}    dec. loss: {:.4f}    BLEU-1: {:.2f}    BLEU-4: {:.2f}"\
                        .format(computation[1], computation[0], validation_bleu_1, validation_bleu_4)

                print ""
                print "Examples:"
                for sent in decoded_validation_sentences[:8]:
                    print "    {}".format(" ".join(sent))
                print ""


